from __future__ import annotations

import argparse
import json

from apps_script_client import AppsScriptClient, AppsScriptError
from env_loader import load_dotenv
from ozon_ord_api import AdminOzonOrdClient, ExternalOzonOrdClient, OzonOrdApiError
from ozon_ord_mapping import (
    admin_statistic_payloads_to_json,
    statistic_payloads_to_json,
)
from sheets_reader import DEFAULT_SHEET_URL, parse_sheet, rows_to_json, validate_rows
from sync_service import (
    build_platform_error_rows,
    build_sync_batch,
    resolve_admin_statistics,
    save_platform_errors,
    sync_batch,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google Sheets -> Ozon ORD sync")
    parser.add_argument(
        "command",
        nargs="?",
        default="preview",
        choices=["preview", "probe-api", "sync"],
    )
    parser.add_argument("--sheet-url", default=DEFAULT_SHEET_URL)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send data to Ozon ORD for the sync command",
    )
    return parser


def preview(sheet_url: str, limit: int) -> int:
    header, rows = parse_sheet(sheet_url)
    issues = validate_rows(rows)
    batch = build_sync_batch(rows)

    print(f"Columns: {len(header)}")
    print(f"Rows parsed: {len(rows)}")
    print(f"Rows with issues: {len(issues)}")
    print(f"Statistics prepared: {len(batch.statistics)}")
    print(f"Mapping errors: {len(batch.mapping_errors)}")

    print("\nSample rows:")
    print(rows_to_json(rows, limit=limit))

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


def probe_api() -> int:
    client = ExternalOzonOrdClient.from_env()
    response = client.list_platforms(page_size=1)
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0


def sync(sheet_url: str, send: bool) -> int:
    _, rows = parse_sheet(sheet_url)
    batch = build_sync_batch(rows)

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
            save_platform_errors(rows, resolution_errors)
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
    try:
        response = sync_batch(external_client, admin_client, batch)
    except OzonOrdApiError as error:
        message = str(error)
        if "Platform not found:" in message:
            errors = message.splitlines()
            save_platform_errors(rows, errors)
            apps_script_client = AppsScriptClient.from_env()
            if apps_script_client is not None:
                apps_script_client.update_platform_errors(
                    build_platform_error_rows(rows, errors)
                )
        raise
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "preview":
            return preview(args.sheet_url, args.limit)
        if args.command == "probe-api":
            return probe_api()
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
