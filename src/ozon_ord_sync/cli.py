from __future__ import annotations

import argparse
import json

from ozon_ord_sync.application.sync_service import (
    build_platform_error_rows,
    build_platform_sync_batch,
    build_sync_batch,
    extract_duplicate_statistic_row_numbers,
    extract_statistic_creation_errors,
    resolve_admin_statistics,
    save_platform_errors,
    sync_batch,
    sync_platform_batch,
)
from ozon_ord_sync.config.env import load_dotenv
from ozon_ord_sync.domain.mapping import (
    admin_statistic_payloads_to_json,
    platform_payloads_to_json,
    statistic_payloads_to_json,
)
from ozon_ord_sync.infrastructure.apps_script import AppsScriptClient, AppsScriptError
from ozon_ord_sync.infrastructure.google_sheets import (
    DEFAULT_PLATFORM_SHEET_NAME,
    DEFAULT_SHEET_URL,
    filter_rows_for_processing,
    parse_platform_sheet,
    parse_sheet,
    rows_to_json,
    validate_platform_rows,
    validate_rows,
)
from ozon_ord_sync.infrastructure.ozon_ord import (
    AdminOzonOrdClient,
    ExternalOzonOrdClient,
    OzonOrdApiError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google Sheets -> Ozon ORD sync")
    parser.add_argument(
        "command",
        nargs="?",
        default="preview",
        choices=["preview", "preview-platforms", "probe-api", "sync", "sync-platforms"],
    )
    parser.add_argument("--sheet-url", default=DEFAULT_SHEET_URL)
    parser.add_argument("--platform-sheet-name", default=DEFAULT_PLATFORM_SHEET_NAME)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send data to Ozon ORD for sync commands",
    )
    return parser


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
    client = ExternalOzonOrdClient.from_env()
    response = client.list_platforms(page_size=1)
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0


def sync_platforms(sheet_url: str, sheet_name: str, send: bool) -> int:
    _, rows = parse_platform_sheet(sheet_url, sheet_name=sheet_name)
    issues = validate_platform_rows(rows)
    batch = build_platform_sync_batch(rows)

    print(f"Platform sheet: {sheet_name}")
    print(f"Rows parsed: {len(rows)}")
    print(f"Rows with issues: {len(issues)}")
    print(f"Platforms prepared: {len(batch.platforms)}")
    print(f"Mapping errors: {len(batch.mapping_errors)}")

    if issues:
        print("\nIssues:")
        for issue in issues[:10]:
            print(f"Row {issue.row_number}: {', '.join(issue.messages)}")
        return 1

    if batch.mapping_errors:
        print("\nMapping errors:")
        for error in batch.mapping_errors[:10]:
            print(error)
        return 1

    if not send:
        print("\nDry run mode. Use --send to push platforms to Ozon ORD.")
        print("\nPlatform payload preview:")
        print(platform_payloads_to_json(batch.platforms, limit=3))
        return 0

    external_client = ExternalOzonOrdClient.from_env()
    response = sync_platform_batch(external_client, batch)
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0


def sync(sheet_url: str, send: bool) -> int:
    _, rows = parse_sheet(sheet_url)
    filtered_rows = filter_rows_for_processing(rows)
    batch = build_sync_batch(filtered_rows)

    print(f"Rows eligible: {len(filtered_rows)}")
    print(f"Statistics prepared: {len(batch.statistics)}")
    print(f"Mapping errors: {len(batch.mapping_errors)}")

    if batch.mapping_errors:
        print("\nMapping errors:")
        for error in batch.mapping_errors[:10]:
            print(error)
        return 1

    if not send:
        external_client = ExternalOzonOrdClient.from_env()
        resolved_statistics, resolution_errors = resolve_admin_statistics(
            external_client, batch
        )
        print("\nDry run mode. Use --send to push data to Ozon ORD.")
        print("\nStatistic payload preview:")
        print(statistic_payloads_to_json(batch.statistics, limit=3))
        if resolution_errors:
            save_platform_errors(filtered_rows, resolution_errors)
            print("\nResolution errors:")
            for error in resolution_errors[:10]:
                print(error)
            print("\nSaved platform lookup errors to platform_errors.json")
            return 1
        print("\nAdmin statistic payload preview:")
        print(
            admin_statistic_payloads_to_json(
                [item.payload for item in resolved_statistics],
                limit=3,
            )
        )
        return 0

    external_client = ExternalOzonOrdClient.from_env()
    admin_client = AdminOzonOrdClient.from_env()
    resolved_statistics, resolution_errors = resolve_admin_statistics(
        external_client, batch
    )
    if resolution_errors:
        save_platform_errors(filtered_rows, resolution_errors)
        apps_script_client = AppsScriptClient.from_env()
        if apps_script_client is not None:
            apps_script_client.update_platform_errors(
                build_platform_error_rows(filtered_rows, resolution_errors)
            )
        raise OzonOrdApiError("\n".join(resolution_errors))

    duplicate_statistic_errors: list[str] = []
    pending_statistics = resolved_statistics
    response: dict[str, object]
    try:
        while True:
            response = sync_batch(
                external_client,
                admin_client,
                batch,
                resolved_statistics=pending_statistics,
            )
            break
    except OzonOrdApiError as error:
        while True:
            message = str(error)
            duplicate_row_numbers = extract_duplicate_statistic_row_numbers(
                message, pending_statistics
            )
            if not duplicate_row_numbers:
                errors = message.splitlines()
                if errors and (
                    "Platform not found:" in message
                    or "Platform matched more than one:" in message
                ):
                    save_platform_errors(filtered_rows, errors)
                    apps_script_client = AppsScriptClient.from_env()
                    if apps_script_client is not None:
                        apps_script_client.update_platform_errors(
                            build_platform_error_rows(filtered_rows, errors)
                        )
                raise

            statistic_errors = extract_statistic_creation_errors(
                message, pending_statistics
            )
            duplicate_statistic_errors.extend(
                error_text
                for error_text in statistic_errors
                if error_text not in duplicate_statistic_errors
            )
            save_platform_errors(filtered_rows, duplicate_statistic_errors)
            apps_script_client = AppsScriptClient.from_env()
            if apps_script_client is not None:
                apps_script_client.update_platform_errors(
                    build_platform_error_rows(filtered_rows, duplicate_statistic_errors)
                )

            skipped_rows = set(duplicate_row_numbers)
            next_pending_statistics = [
                item
                for item in pending_statistics
                if item.row_number not in skipped_rows
            ]
            if len(next_pending_statistics) == len(pending_statistics):
                raise
            pending_statistics = next_pending_statistics

            if not pending_statistics:
                response = {"statistic_response": None}
                break

            try:
                response = sync_batch(
                    external_client,
                    admin_client,
                    batch,
                    resolved_statistics=pending_statistics,
                )
                break
            except OzonOrdApiError as next_error:
                error = next_error
                continue

    if duplicate_statistic_errors:
        response["skipped_errors"] = duplicate_statistic_errors
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "preview":
            return preview(args.sheet_url, args.limit)
        if args.command == "preview-platforms":
            return preview_platforms(
                args.sheet_url, args.platform_sheet_name, args.limit
            )
        if args.command == "probe-api":
            return probe_api()
        if args.command == "sync-platforms":
            return sync_platforms(args.sheet_url, args.platform_sheet_name, args.send)
        return sync(args.sheet_url, args.send)
    except OzonOrdApiError as error:
        print(f"API error: {error}")
        return 1
    except AppsScriptError as error:
        print(f"Apps Script error: {error}")
        return 1
    except Exception as error:
        print(f"Error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
