from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ozon_ord_sync.application.sheet_parser import (
    filter_rows_for_processing,
    parse_platform_sheet,
    parse_sheet,
    validate_platform_rows,
)
from ozon_ord_sync.application.sync_service import (
    build_platform_error_rows,
    build_platform_sync_batch,
    build_sync_batch,
    resolve_admin_statistics,
    save_platform_errors,
    sync_batch_skipping_duplicate_statistics,
    sync_platform_batch,
)
from ozon_ord_sync.config.factories import (
    build_admin_ozon_ord_client_from_env,
    build_apps_script_client_from_env,
    build_external_ozon_ord_client_from_env,
)
from ozon_ord_sync.domain.models import ParsedRow
from ozon_ord_sync.infrastructure.ozon_ord import OzonOrdApiError


@dataclass
class PlatformSyncResult:
    ok: bool
    sheet_name: str
    rows_parsed: int
    rows_with_issues: int
    platforms_prepared: int
    mapping_errors: list[str]
    issues: list[str]
    dry_run: bool
    ozon_response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StatisticsSyncResult:
    ok: bool
    rows_eligible: int
    statistics_prepared: int
    mapping_errors: list[str]
    resolution_errors: list[str]
    dry_run: bool
    ozon_response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_platform_sync(
    sheet_url: str,
    sheet_name: str,
    send: bool,
) -> PlatformSyncResult:
    _, rows = parse_platform_sheet(sheet_url, sheet_name=sheet_name)
    issues = validate_platform_rows(rows)
    batch = build_platform_sync_batch(rows)
    issue_messages = [
        f"Row {issue.row_number}: {', '.join(issue.messages)}" for issue in issues
    ]

    result = PlatformSyncResult(
        ok=not issues and not batch.mapping_errors,
        sheet_name=sheet_name,
        rows_parsed=len(rows),
        rows_with_issues=len(issues),
        platforms_prepared=len(batch.platforms),
        mapping_errors=batch.mapping_errors,
        issues=issue_messages,
        dry_run=not send,
    )
    if not result.ok or not send:
        return result

    external_client = build_external_ozon_ord_client_from_env()
    result.ozon_response = sync_platform_batch(external_client, batch)
    return result


def run_statistics_sync(sheet_url: str, send: bool) -> StatisticsSyncResult:
    _, rows = parse_sheet(sheet_url)
    filtered_rows = filter_rows_for_processing(rows)
    batch = build_sync_batch(filtered_rows)

    result = StatisticsSyncResult(
        ok=not batch.mapping_errors,
        rows_eligible=len(filtered_rows),
        statistics_prepared=len(batch.statistics),
        mapping_errors=batch.mapping_errors,
        resolution_errors=[],
        dry_run=not send,
    )
    if batch.mapping_errors:
        return result

    external_client = build_external_ozon_ord_client_from_env()
    resolved_statistics, resolution_errors = resolve_admin_statistics(
        external_client, batch
    )
    result.resolution_errors = resolution_errors
    if resolution_errors:
        result.ok = False
        if send:
            _publish_platform_errors(filtered_rows, resolution_errors)
            raise OzonOrdApiError("\n".join(resolution_errors))
        save_platform_errors(filtered_rows, resolution_errors)
        return result

    if not send:
        return result

    admin_client = build_admin_ozon_ord_client_from_env()
    try:
        result.ozon_response = sync_batch_skipping_duplicate_statistics(
            external_client,
            admin_client,
            batch,
            resolved_statistics,
            on_duplicate_errors=lambda errors: _publish_platform_errors(
                filtered_rows, errors
            ),
        )
    except OzonOrdApiError as error:
        message = str(error)
        errors = message.splitlines()
        if errors and (
            "Platform not found:" in message
            or "Platform matched more than one:" in message
        ):
            _publish_platform_errors(filtered_rows, errors)
        raise
    return result


def _publish_platform_errors(rows: list[ParsedRow], errors: list[str]) -> None:
    save_platform_errors(rows, errors)
    apps_script_client = build_apps_script_client_from_env()
    if apps_script_client is not None:
        apps_script_client.update_platform_errors(
            build_platform_error_rows(rows, errors)
        )
