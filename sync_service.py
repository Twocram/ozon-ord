from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ozon_ord_api import AdminOzonOrdClient, ExternalOzonOrdClient, OzonOrdApiError
from ozon_ord_mapping import (
    OzonOrdAdminStatisticPayload,
    OzonOrdPlatformPayload,
    OzonOrdStatisticPayload,
    build_platform_payload,
    build_statistic_payload,
)
from sheets_reader import ParsedRow


@dataclass
class SyncBatch:
    platforms: list[OzonOrdPlatformPayload]
    statistics: list[OzonOrdStatisticPayload]
    mapping_errors: list[str]


@dataclass
class ResolvedStatisticPayload:
    row_number: int
    payload: OzonOrdAdminStatisticPayload


def build_sync_batch(rows: list[ParsedRow]) -> SyncBatch:
    platforms_by_id: dict[str, OzonOrdPlatformPayload] = {}
    statistics: list[OzonOrdStatisticPayload] = []
    mapping_errors: list[str] = []

    for row in rows:
        try:
            platform_payload = build_platform_payload(row)
            statistic_payload = build_statistic_payload(row)
        except ValueError as error:
            mapping_errors.append(str(error))
            continue

        platforms_by_id[platform_payload.externalPlatformId] = platform_payload
        statistics.append(statistic_payload)

    return SyncBatch(
        platforms=list(platforms_by_id.values()),
        statistics=statistics,
        mapping_errors=mapping_errors,
    )


def resolve_admin_statistics(
    client: ExternalOzonOrdClient,
    batch: SyncBatch,
) -> tuple[list[ResolvedStatisticPayload], list[str]]:
    platform_urls = {
        payload.externalPlatformId: payload.url for payload in batch.platforms
    }
    platform_ids, platform_errors = resolve_platform_ids(
        client,
        platform_urls,
    )
    creative_ids, creative_errors = resolve_creative_ids(
        client,
        [payload.externalCreativeId for payload in batch.statistics],
    )

    resolved: list[ResolvedStatisticPayload] = []
    errors: list[str] = list(platform_errors) + list(creative_errors)

    for payload in batch.statistics:
        platform_id = platform_ids.get(payload.externalPlatformId)
        if platform_id is None:
            errors.append(
                f"Platform not found: externalPlatformId={payload.externalPlatformId}"
            )
            continue

        creative_id = creative_ids.get(payload.externalCreativeId)
        if creative_id is None:
            errors.append(f"Creative not found for marker={payload.externalCreativeId}")
            continue

        resolved.append(
            ResolvedStatisticPayload(
                row_number=_extract_row_number(payload.comment),
                payload=OzonOrdAdminStatisticPayload(
                    creativeId=creative_id,
                    platformId=platform_id,
                    price={
                        "amount": payload.moneySpent.rstrip("0").rstrip(".")
                        if "." in payload.moneySpent
                        else payload.moneySpent,
                        "vatRate": "",
                        "withNdsSelected": False,
                        "excludingAmount": payload.moneySpent.rstrip("0").rstrip(".")
                        if "." in payload.moneySpent
                        else payload.moneySpent,
                        "manualCalc": False,
                    },
                    comment="",
                    dateEndFact=payload.dateEndFact,
                    dateEndPlan=payload.dateEndPlan,
                    paymentType="PAYMENT_TYPE_OTHER",
                    dateStartFact=payload.dateStartFact,
                    dateStartPlan=payload.dateStartPlan,
                    unitCost=payload.unitCost.rstrip("0").rstrip(".")
                    if "." in payload.unitCost
                    else payload.unitCost,
                    viewsCountByFact=payload.viewsCountByFact,
                    viewsCountByInvoice=payload.viewsCountByInvoice,
                    sameDate=True,
                    sameViews=True,
                    isAutoCalc=True,
                    isSelfPromo=False,
                    isNative=False,
                    externalId="",
                    fromDate="",
                    toDate="",
                ),
            )
        )

    return resolved, errors


def sync_batch(
    external_client: ExternalOzonOrdClient,
    admin_client: AdminOzonOrdClient,
    batch: SyncBatch,
    resolved_statistics: list[ResolvedStatisticPayload] | None = None,
) -> dict[str, object]:
    statistic_response = None

    if resolved_statistics is None:
        resolved_statistics, resolution_errors = resolve_admin_statistics(
            external_client, batch
        )
        if resolution_errors:
            raise OzonOrdApiError("\n".join(resolution_errors))

    if resolved_statistics:
        statistic_response = admin_client.add_statistics(
            [item.payload.__dict__ for item in resolved_statistics]
        )

    return {
        "statistic_response": statistic_response,
    }


def resolve_platform_ids(
    client: ExternalOzonOrdClient,
    external_platform_urls: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    target_urls = {
        url.rstrip("/"): external_id
        for external_id, url in external_platform_urls.items()
    }
    found_by_external_id: dict[str, str] = {}
    matches_by_external_id: dict[str, list[str]] = {external_id: [] for external_id in target_urls.values()}
    errors: list[str] = []
    cursor_external_id = ""
    cursor_updated_at = None

    for _ in range(50):
        response = client.list_platforms_page(
            cursor_external_id=cursor_external_id,
            cursor_updated_at=cursor_updated_at,
            page_size=2500,
        )
        platforms = response.get("platform", [])
        if not platforms:
            break

        for platform in platforms:
            external_id = platform.get("externalId")
            platform_id = platform.get("platformId")
            platform_url = (platform.get("url") or "").rstrip("/")
            matched_external_id = target_urls.get(platform_url)
            if matched_external_id and platform_id:
                matches = matches_by_external_id[matched_external_id]
                if platform_id not in matches:
                    matches.append(platform_id)

        last = platforms[-1]
        cursor_external_id = last.get("externalId") or ""
        updated_at = last.get("updatedAt")
        cursor_updated_at = {"updatedAt": updated_at} if updated_at else None

    for external_id, matches in matches_by_external_id.items():
        if len(matches) == 1:
            found_by_external_id[external_id] = matches[0]
        elif len(matches) > 1:
            errors.append(f"Platform matched more than one: {external_id}")

    return found_by_external_id, errors


def resolve_creative_ids(
    client: ExternalOzonOrdClient,
    markers: list[str],
) -> tuple[dict[str, str], list[str]]:
    target_markers = set(markers)
    found: dict[str, str] = {}
    cursor_external_id = ""
    cursor_updated_at = None
    errors: list[str] = []

    for _ in range(50):
        response = client.list_creatives(
            cursor_external_id=cursor_external_id,
            cursor_updated_at=cursor_updated_at,
            page_size=2500,
        )
        creatives = response.get("creative", [])
        if not creatives:
            break

        for creative in creatives:
            marker = creative.get("marker")
            creative_id = creative.get("creativeId")
            if marker in target_markers and creative_id:
                found[marker] = creative_id

        if target_markers.issubset(found.keys()):
            break

        last = creatives[-1]
        cursor_external_id = last.get("externalCreativeId") or ""
        updated_at = last.get("updatedAt")
        cursor_updated_at = {"updatedAt": updated_at} if updated_at else None

    for marker in target_markers:
        if marker not in found:
            errors.append(f"Creative marker not found: {marker}")

    return found, errors


def _extract_row_number(comment: str) -> int:
    tail = comment.rsplit(" ", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def save_platform_errors(rows: list[ParsedRow], errors: list[str], path: str = "platform_errors.json") -> None:
    payload = build_platform_error_payload(rows, errors)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_platform_error_rows(rows: list[ParsedRow], errors: list[str]) -> list[dict[str, object]]:
    payload = build_platform_error_payload(rows, errors)
    return payload["rows"]


def build_platform_error_payload(rows: list[ParsedRow], errors: list[str]) -> dict[str, object]:
    error_by_external_platform_id: dict[str, str] = {}
    error_by_row_number: dict[int, str] = {}
    for error in errors:
        if row_error := _parse_row_error(error):
            error_by_row_number[row_error[0]] = row_error[1]
        elif error.startswith("Platform not found: "):
            external_id = _normalize_platform_error_external_id(error.split(": ", 1)[1])
            error_by_external_platform_id[external_id] = "Площака не найдена"
        elif error.startswith("Platform matched more than one: "):
            external_id = _normalize_platform_error_external_id(error.split(": ", 1)[1])
            error_by_external_platform_id[external_id] = "Найдено больше одной"

    return {
        "rows": [
            {
                "row_number": row.row_number,
                "creative_id": row.creative_id,
                "channel_url": row.channel_url,
                "platform_error": error_by_row_number.get(row.row_number)
                or error_by_external_platform_id[_row_external_platform_id(row)],
            }
            for row in rows
            if row.row_number in error_by_row_number
            or (
                row.channel_url is not None
                and _row_external_platform_id(row) in error_by_external_platform_id
            )
        ],
        "errors": errors,
    }


def _row_external_platform_id(row: ParsedRow) -> str | None:
    try:
        return build_platform_payload(row).externalPlatformId
    except ValueError:
        return None


def _normalize_platform_error_external_id(value: str) -> str:
    prefix = "externalPlatformId="
    if value.startswith(prefix):
        return value[len(prefix):]
    return value


def extract_statistic_creation_errors(
    error_message: str,
    resolved_statistics: list[ResolvedStatisticPayload],
) -> list[str]:
    duplicate_message = "Статистика уже создана"
    if duplicate_message not in error_message:
        return []

    row_numbers: set[int] = set()
    indexed_rows = {
        index: item.row_number for index, item in enumerate(resolved_statistics)
    }
    creative_rows = {
        item.payload.creativeId: item.row_number for item in resolved_statistics
    }

    payload = _extract_json_payload_from_error_message(error_message)
    if payload is not None:
        for entry in _collect_duplicate_statistic_entries(payload):
            row_number = (
                entry.get("row_number")
                or indexed_rows.get(entry.get("index"))
                or creative_rows.get(entry.get("creative_id"))
            )
            if row_number:
                row_numbers.add(row_number)

    if not row_numbers and len(resolved_statistics) == 1:
        row_numbers.add(resolved_statistics[0].row_number)

    return [f"Row {row_number}: {duplicate_message}" for row_number in sorted(row_numbers)]


def split_resolution_errors(errors: list[str]) -> tuple[list[str], list[str]]:
    non_blocking_prefixes = (
        "Platform not found: ",
        "Platform matched more than one: ",
    )
    non_blocking: list[str] = []
    blocking: list[str] = []

    for error in errors:
        if error.startswith(non_blocking_prefixes):
            non_blocking.append(error)
        else:
            blocking.append(error)

    return non_blocking, blocking


def _parse_row_error(error: str) -> tuple[int, str] | None:
    match = re.match(r"^Row (\d+): (.+)$", error)
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def _extract_json_payload_from_error_message(error_message: str) -> Any | None:
    for start_char in ("{", "["):
        start = error_message.find(start_char)
        if start == -1:
            continue
        try:
            return json.loads(error_message[start:])
        except json.JSONDecodeError:
            continue
    return None


def _collect_duplicate_statistic_entries(payload: Any) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            messages = [
                value
                for key, value in node.items()
                if key in {"message", "error", "detail", "description", "text"}
                and isinstance(value, str)
            ]
            if any("Статистика уже создана" in message for message in messages):
                collected.append(
                    {
                        "index": _extract_index_from_node(node),
                        "creative_id": _extract_creative_id_from_node(node),
                        "row_number": _extract_row_number_from_node(node),
                    }
                )

            for value in node.values():
                walk(value)
            return

        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return collected


def _extract_index_from_node(node: dict[str, Any]) -> int | None:
    direct_index = node.get("index")
    if isinstance(direct_index, int):
        return direct_index

    for key in ("path", "field", "name"):
        value = node.get(key)
        if not isinstance(value, str):
            continue
        match = re.search(r"statistics\[(\d+)\]", value)
        if match:
            return int(match.group(1))
    return None


def _extract_creative_id_from_node(node: dict[str, Any]) -> str | None:
    for key in ("creativeId", "creative_id", "externalCreativeId", "marker"):
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_row_number_from_node(node: dict[str, Any]) -> int | None:
    for key in ("rowNumber", "row_number"):
        value = node.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None
