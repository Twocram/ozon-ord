from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlparse

from ozon_ord_sync.domain.mapping import (
    build_platform_payload,
    build_platform_sheet_payload,
    build_statistic_payload,
)
from ozon_ord_sync.domain.models import (
    OzonOrdAdminStatisticPayload,
    OzonOrdPlatformPayload,
    OzonOrdStatisticPayload,
    ParsedPlatformRow,
    ParsedRow,
    PlatformSyncBatch,
    ResolvedStatisticPayload,
    SyncBatch,
)
from ozon_ord_sync.infrastructure.ozon_ord import (
    AdminOzonOrdClient,
    ExternalOzonOrdClient,
    OzonOrdApiError,
)


class PlatformErrorPayload(TypedDict):
    rows: list[dict[str, object]]
    errors: list[str]


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


def build_platform_sync_batch(rows: list[ParsedPlatformRow]) -> PlatformSyncBatch:
    platforms_by_id: dict[str, OzonOrdPlatformPayload] = {}
    mapping_errors: list[str] = []

    for row in rows:
        try:
            platform_payload = build_platform_sheet_payload(row)
        except ValueError as error:
            mapping_errors.append(str(error))
            continue

        platforms_by_id[platform_payload.externalPlatformId] = platform_payload

    return PlatformSyncBatch(
        platforms=list(platforms_by_id.values()),
        mapping_errors=mapping_errors,
    )


def sync_platform_batch(
    external_client: ExternalOzonOrdClient,
    batch: PlatformSyncBatch,
) -> dict[str, object]:
    platform_response = None
    if batch.platforms:
        platform_response = external_client.register_or_update_platforms(
            batch.platforms
        )

    return {
        "platform_response": platform_response,
    }


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


def sync_batch_skipping_duplicate_statistics(
    external_client: ExternalOzonOrdClient,
    admin_client: AdminOzonOrdClient,
    batch: SyncBatch,
    resolved_statistics: list[ResolvedStatisticPayload],
    on_duplicate_errors: Callable[[list[str]], None] | None = None,
) -> dict[str, object]:
    duplicate_statistic_errors: list[str] = []
    pending_statistics = resolved_statistics

    while pending_statistics:
        try:
            response = sync_batch(
                external_client,
                admin_client,
                batch,
                resolved_statistics=pending_statistics,
            )
            break
        except OzonOrdApiError as error:
            message = str(error)
            duplicate_row_numbers = extract_duplicate_statistic_row_numbers(
                message, pending_statistics
            )
            if not duplicate_row_numbers:
                raise

            statistic_errors = extract_statistic_creation_errors(
                message, pending_statistics
            )
            duplicate_statistic_errors.extend(
                error_text
                for error_text in statistic_errors
                if error_text not in duplicate_statistic_errors
            )
            if on_duplicate_errors is not None:
                on_duplicate_errors(duplicate_statistic_errors)

            skipped_rows = set(duplicate_row_numbers)
            next_pending_statistics = [
                item
                for item in pending_statistics
                if item.row_number not in skipped_rows
            ]
            if len(next_pending_statistics) == len(pending_statistics):
                raise
            pending_statistics = next_pending_statistics
    else:
        response = {"statistic_response": None}

    if duplicate_statistic_errors:
        response["skipped_errors"] = duplicate_statistic_errors

    return response


def resolve_platform_ids(
    client: ExternalOzonOrdClient,
    external_platform_urls: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    target_urls: dict[str, list[str]] = {}
    for external_id, url in external_platform_urls.items():
        target_urls.setdefault(_canonical_platform_url(url), []).append(external_id)
    found_by_external_id: dict[str, str] = {}
    matches_by_external_id: dict[str, list[str]] = {
        external_id: [] for external_id in external_platform_urls
    }
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
            platform_url = _canonical_platform_url(platform.get("url") or "")
            matched_external_ids = target_urls.get(platform_url, [])
            if platform_id:
                for matched_external_id in matched_external_ids:
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
    targets_by_casefold: dict[str, list[str]] = {}
    for marker in target_markers:
        targets_by_casefold.setdefault(marker.casefold(), []).append(marker)
    casefold_matches: dict[str, list[str]] = {
        marker: [] for marker in target_markers
    }
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
            elif isinstance(marker, str) and creative_id:
                for target in targets_by_casefold.get(marker.casefold(), []):
                    if creative_id not in casefold_matches[target]:
                        casefold_matches[target].append(creative_id)

        if target_markers.issubset(found.keys()):
            break

        last = creatives[-1]
        cursor_external_id = last.get("externalCreativeId") or ""
        updated_at = last.get("updatedAt")
        cursor_updated_at = {"updatedAt": updated_at} if updated_at else None

    for marker in target_markers:
        if marker not in found and len(casefold_matches[marker]) == 1:
            found[marker] = casefold_matches[marker][0]
        if marker not in found:
            errors.append(f"Creative marker not found: {marker}")

    return found, errors


def _canonical_platform_url(url: str) -> str:
    normalized = url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (parsed.hostname or "").casefold() in {"t.me", "www.t.me", "telegram.me"}:
        first_path_part = parsed.path.strip("/").split("/", 1)[0]
        if first_path_part and not first_path_part.startswith("+"):
            first_path_part = first_path_part.casefold()
        return f"https://t.me/{first_path_part}"
    return normalized


def _extract_row_number(comment: str) -> int:
    tail = comment.rsplit(" ", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def save_platform_errors(
    rows: list[ParsedRow], errors: list[str], path: str = "platform_errors.json"
) -> None:
    payload = build_platform_error_payload(rows, errors)
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_platform_error_rows(
    rows: list[ParsedRow], errors: list[str]
) -> list[dict[str, object]]:
    payload = build_platform_error_payload(rows, errors)
    return payload["rows"]


def build_platform_error_payload(
    rows: list[ParsedRow], errors: list[str]
) -> PlatformErrorPayload:
    error_by_external_platform_id: dict[str, str] = {}
    error_by_row_number: dict[int, str] = {}
    for error in errors:
        if row_error := _parse_row_error(error):
            error_by_row_number[row_error[0]] = row_error[1]
        elif error.startswith("Platform not found: "):
            external_id = _normalize_platform_error_external_id(error.split(": ", 1)[1])
            error_by_external_platform_id[external_id] = "Площадка не найдена"
        elif error.startswith("Platform matched more than one: "):
            external_id = _normalize_platform_error_external_id(error.split(": ", 1)[1])
            error_by_external_platform_id[external_id] = "Найдено больше одной площадки"

    error_rows: list[dict[str, object]] = []
    for row in rows:
        row_error = error_by_row_number.get(row.row_number)
        external_platform_id = _row_external_platform_id(row)
        platform_error = (
            error_by_external_platform_id.get(external_platform_id)
            if external_platform_id is not None
            else None
        )
        error = row_error or platform_error
        if error is None:
            continue

        error_rows.append(
            {
                "row_number": row.row_number,
                "creative_id": row.creative_id,
                "channel_url": row.channel_url,
                "error": error,
                "platform_error": error,
            }
        )

    return {"rows": error_rows, "errors": errors}


def _row_external_platform_id(row: ParsedRow) -> str | None:
    try:
        return build_platform_payload(row).externalPlatformId
    except ValueError:
        return None


def _normalize_platform_error_external_id(value: str) -> str:
    prefix = "externalPlatformId="
    if value.startswith(prefix):
        return value[len(prefix) :]
    return value


def extract_statistic_creation_errors(
    error_message: str,
    resolved_statistics: list[ResolvedStatisticPayload],
) -> list[str]:
    details_by_row = _duplicate_statistic_details_by_row(
        error_message, resolved_statistics
    )
    return [
        f"Row {row_number}: {details_by_row.get(row_number, 'Креатив уже есть в базе')}"
        for row_number in extract_duplicate_statistic_row_numbers(
            error_message, resolved_statistics
        )
    ]


def extract_duplicate_statistic_row_numbers(
    error_message: str,
    resolved_statistics: list[ResolvedStatisticPayload],
) -> list[int]:
    return sorted(
        _duplicate_statistic_details_by_row(error_message, resolved_statistics).keys()
    )


def _duplicate_statistic_details_by_row(
    error_message: str,
    resolved_statistics: list[ResolvedStatisticPayload],
) -> dict[int, str]:
    if not _is_duplicate_statistic_error(error_message):
        return {}

    details_by_row: dict[int, str] = {}
    indexed_rows = {
        index: item.row_number for index, item in enumerate(resolved_statistics)
    }
    creative_rows = {
        item.payload.creativeId: item.row_number for item in resolved_statistics
    }
    keyed_rows: dict[tuple[str, str, str], int] = {}
    for item in resolved_statistics:
        payload = item.payload
        for month in {
            payload.dateStartFact.strftime("%Y-%m"),
            payload.dateEndFact.strftime("%Y-%m"),
        }:
            keyed_rows[(payload.creativeId, payload.platformId, month)] = item.row_number

    entries = _collect_duplicate_statistic_entries_from_text(error_message)
    payload = _extract_json_payload_from_error_message(error_message)
    if payload is not None:
        entries.extend(_collect_duplicate_statistic_entries(payload))

    for entry in entries:
        row_number = entry.get("row_number")
        index = entry.get("index")
        creative_id = entry.get("creative_id")
        platform_id = entry.get("platform_id")
        month = entry.get("month")
        if row_number is None and isinstance(index, int):
            row_number = indexed_rows.get(index)
        if (
            row_number is None
            and isinstance(creative_id, str)
            and isinstance(platform_id, str)
            and isinstance(month, str)
        ):
            row_number = keyed_rows.get((creative_id, platform_id, month))
        if row_number is None and isinstance(creative_id, str):
            row_number = creative_rows.get(creative_id)
        if row_number:
            details_by_row[row_number] = _format_duplicate_statistic_error(entry)

    if not details_by_row and len(resolved_statistics) == 1:
        details_by_row[resolved_statistics[0].row_number] = "Креатив уже есть в базе"

    return details_by_row


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


def _is_duplicate_statistic_error(error_message: str) -> bool:
    return any(
        marker in error_message
        for marker in ("Статистика уже создана", "Продублирована статистика")
    )


def _collect_duplicate_statistic_entries_from_text(
    text: str,
) -> list[dict[str, Any]]:
    return [
        {
            "creative_id": match.group(1),
            "platform_id": match.group(2),
            "month": match.group(3),
        }
        for match in re.finditer(
            r"Продублирована статистика для креатива:\s*(\d+)\s+"
            r"и площадки:\s*(\d+)\s+за данный месяц:\s*(\d{4}-\d{2})",
            text,
        )
    ]


def _format_duplicate_statistic_error(entry: dict[str, Any]) -> str:
    creative_id = entry.get("creative_id")
    platform_id = entry.get("platform_id")
    month = entry.get("month")
    if creative_id and platform_id and month:
        return f"Дубль статистики: креатив {creative_id}, площадка {platform_id}, месяц {month}"
    return "Креатив уже есть в базе"


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
            if any(_is_duplicate_statistic_error(message) for message in messages):
                text_entries = [
                    entry
                    for message in messages
                    for entry in _collect_duplicate_statistic_entries_from_text(message)
                ]
                collected.extend(text_entries)
                if not text_entries:
                    collected.append(
                        {
                            "index": _extract_index_from_node(node),
                            "creative_id": _extract_creative_id_from_node(node),
                            "platform_id": _extract_platform_id_from_node(node),
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


def _extract_platform_id_from_node(node: dict[str, Any]) -> str | None:
    for key in ("platformId", "platform_id", "externalPlatformId"):
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
