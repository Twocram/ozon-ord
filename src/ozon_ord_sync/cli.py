from __future__ import annotations

import argparse

from ozon_ord_sync.application.commands import (
    preview,
    preview_platforms,
    probe_api,
    sync,
    sync_platforms,
)
from ozon_ord_sync.config.env import load_dotenv
from ozon_ord_sync.infrastructure.apps_script import AppsScriptError
from ozon_ord_sync.infrastructure.google_sheets import (
    DEFAULT_PLATFORM_SHEET_NAME,
    DEFAULT_SHEET_URL,
)
from ozon_ord_sync.infrastructure.api_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    run_api_server,
)
from ozon_ord_sync.infrastructure.ozon_ord import OzonOrdApiError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google Sheets -> Ozon ORD sync")
    parser.add_argument(
        "command",
        nargs="?",
        default="preview",
        choices=[
            "preview",
            "preview-platforms",
            "probe-api",
            "sync",
            "sync-platforms",
            "api",
        ],
    )
    parser.add_argument("--sheet-url", default=DEFAULT_SHEET_URL)
    parser.add_argument("--platform-sheet-name", default=DEFAULT_PLATFORM_SHEET_NAME)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send data to Ozon ORD for sync commands",
    )
    parser.add_argument("--api-host", default=DEFAULT_HOST)
    parser.add_argument("--api-port", type=int, default=DEFAULT_PORT)
    return parser


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
        if args.command == "api":
            run_api_server(args.api_host, args.api_port)
            return 0
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
