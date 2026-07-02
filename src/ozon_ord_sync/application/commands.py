from __future__ import annotations

import json

from ozon_ord_sync.application.sync_workflows import (
    run_platform_preview,
    run_platform_sync,
    run_statistics_preview,
    run_statistics_sync,
)
from ozon_ord_sync.config.factories import build_external_ozon_ord_client_from_env


def preview(sheet_url: str, limit: int) -> int:
    result = run_statistics_preview(sheet_url, limit)

    print(f"Rows parsed: {result.rows_parsed}")
    print(f"Rows eligible: {result.rows_eligible}")
    print(f"Rows skipped by executor filter: {result.rows_skipped_by_executor}")
    print(f"Rows with issues: {result.rows_with_issues}")
    print(f"Statistics prepared: {result.statistics_prepared}")
    print(f"Mapping errors: {len(result.mapping_errors)}")

    print("\nSample rows:")
    print(json.dumps(result.sample_rows, ensure_ascii=False, indent=2, default=str))

    print("\nSample statistic payloads:")
    print(
        json.dumps(
            result.sample_statistics,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    if result.issues:
        print("\nIssues:")
        for issue in result.issues[:10]:
            print(issue)

    if result.mapping_errors:
        print("\nMapping errors:")
        for error in result.mapping_errors[:10]:
            print(error)

    return 0


def preview_platforms(sheet_url: str, sheet_name: str, limit: int) -> int:
    result = run_platform_preview(sheet_url, sheet_name, limit)

    print(f"Platform sheet: {result.sheet_name}")
    print(f"Rows parsed: {result.rows_parsed}")
    print(f"Rows with issues: {result.rows_with_issues}")
    print(f"Platforms prepared: {result.platforms_prepared}")
    print(f"Mapping errors: {len(result.mapping_errors)}")

    print("\nSample rows:")
    print(json.dumps(result.sample_rows, ensure_ascii=False, indent=2, default=str))

    print("\nSample platform payloads:")
    print(
        json.dumps(
            result.sample_platforms,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    if result.issues:
        print("\nIssues:")
        for issue in result.issues[:10]:
            print(issue)

    if result.mapping_errors:
        print("\nMapping errors:")
        for error in result.mapping_errors[:10]:
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
