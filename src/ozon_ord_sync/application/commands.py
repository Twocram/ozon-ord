from __future__ import annotations

import json

from ozon_ord_sync.application.formatting import (
    platform_payloads_to_json,
    statistic_payloads_to_json,
)
from ozon_ord_sync.application.sheet_parser import (
    filter_rows_for_processing,
    parse_platform_sheet,
    parse_sheet,
    rows_to_json,
    validate_platform_rows,
    validate_rows,
)
from ozon_ord_sync.application.sync_service import (
    build_platform_sync_batch,
    build_sync_batch,
)
from ozon_ord_sync.application.sync_workflows import (
    run_platform_sync,
    run_statistics_sync,
)
from ozon_ord_sync.config.factories import build_external_ozon_ord_client_from_env


def preview(sheet_url: str, limit: int) -> int:
    header, rows = parse_sheet(sheet_url)
    filtered_rows = filter_rows_for_processing(rows)
    issues = validate_rows(filtered_rows)
    batch = build_sync_batch(filtered_rows)

    print(f"Columns: {len(header)}")
    print(f"Rows parsed: {len(rows)}")
    print(f"Rows eligible: {len(filtered_rows)}")
    print(f"Rows skipped by executor filter: {len(rows) - len(filtered_rows)}")
    print(f"Rows with issues: {len(issues)}")
    print(f"Statistics prepared: {len(batch.statistics)}")
    print(f"Mapping errors: {len(batch.mapping_errors)}")

    print("\nSample rows:")
    print(rows_to_json(filtered_rows, limit=limit))

    print("\nSample statistic payloads:")
    print(statistic_payloads_to_json(batch.statistics, limit=limit))

    if issues:
        print("\nIssues:")
        for issue in issues[:10]:
            print(f"Row {issue.row_number}: {', '.join(issue.messages)}")

    if batch.mapping_errors:
        print("\nMapping errors:")
        for error in batch.mapping_errors[:10]:
            print(error)

    return 0


def preview_platforms(sheet_url: str, sheet_name: str, limit: int) -> int:
    header, rows = parse_platform_sheet(sheet_url, sheet_name=sheet_name)
    issues = validate_platform_rows(rows)
    batch = build_platform_sync_batch(rows)

    print(f"Platform sheet: {sheet_name}")
    print(f"Columns: {len(header)}")
    print(f"Rows parsed: {len(rows)}")
    print(f"Rows with issues: {len(issues)}")
    print(f"Platforms prepared: {len(batch.platforms)}")
    print(f"Mapping errors: {len(batch.mapping_errors)}")

    print("\nSample rows:")
    print(rows_to_json(rows, limit=limit))

    print("\nSample platform payloads:")
    print(platform_payloads_to_json(batch.platforms, limit=limit))

    if issues:
        print("\nIssues:")
        for issue in issues[:10]:
            print(f"Row {issue.row_number}: {', '.join(issue.messages)}")

    if batch.mapping_errors:
        print("\nMapping errors:")
        for error in batch.mapping_errors[:10]:
            print(error)

    return 0


def probe_api() -> int:
    client = build_external_ozon_ord_client_from_env()
    response = client.list_platforms(page_size=1)
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0


def sync_platforms(sheet_url: str, sheet_name: str, send: bool) -> int:
    result = run_platform_sync(sheet_url, sheet_name, send)

    print(f"Platform sheet: {result.sheet_name}")
    print(f"Rows parsed: {result.rows_parsed}")
    print(f"Rows with issues: {result.rows_with_issues}")
    print(f"Platforms prepared: {result.platforms_prepared}")
    print(f"Mapping errors: {len(result.mapping_errors)}")

    if result.issues:
        print("\nIssues:")
        for issue in result.issues[:10]:
            print(issue)
        return 1

    if result.mapping_errors:
        print("\nMapping errors:")
        for error in result.mapping_errors[:10]:
            print(error)
        return 1

    if result.dry_run:
        print("\nDry run mode. Use --send to push platforms to Ozon ORD.")
        return 0

    print(json.dumps(result.ozon_response, ensure_ascii=False, indent=2, default=str))
    return 0


def sync(sheet_url: str, send: bool) -> int:
    result = run_statistics_sync(sheet_url, send)

    print(f"Rows eligible: {result.rows_eligible}")
    print(f"Statistics prepared: {result.statistics_prepared}")
    print(f"Mapping errors: {len(result.mapping_errors)}")

    if result.mapping_errors:
        print("\nMapping errors:")
        for error in result.mapping_errors[:10]:
            print(error)
        return 1

    if result.dry_run:
        print("\nDry run mode. Use --send to push data to Ozon ORD.")
        if result.resolution_errors:
            print("\nResolution errors:")
            for error in result.resolution_errors[:10]:
                print(error)
            print("\nSaved platform lookup errors to platform_errors.json")
            return 1
        return 0

    print(json.dumps(result.ozon_response, ensure_ascii=False, indent=2, default=str))
    return 0