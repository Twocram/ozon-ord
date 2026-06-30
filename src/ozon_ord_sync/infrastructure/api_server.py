from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ozon_ord_sync.application.sync_workflows import (
    run_platform_sync,
    run_statistics_sync,
)
from ozon_ord_sync.config.runtime_auth import (
    apply_stored_ozon_cookie,
    save_ozon_cookie,
    stored_cookie_status,
)
from ozon_ord_sync.infrastructure.google_sheets import (
    DEFAULT_PLATFORM_SHEET_NAME,
    DEFAULT_SHEET_URL,
)

API_TOKEN_ENV = "OZON_ORD_SYNC_API_TOKEN"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class ApiServerError(RuntimeError):
    pass


def run_api_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    token = os.getenv(API_TOKEN_ENV)
    if not token:
        raise ApiServerError(f"Environment variable {API_TOKEN_ENV} is required")

    server = ThreadingHTTPServer((host, port), _ApiHandler)
    print(f"Ozon ORD Sync API listening on http://{host}:{port}")
    server.serve_forever()


class _ApiHandler(BaseHTTPRequestHandler):
    server_version = "OzonOrdSyncApi/0.1"

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        if self.path != "/api/status":
            self._send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return
        if not self._authorize():
            return

        cookie_status = stored_cookie_status()
        self._send_json(
            {
                "ok": True,
                **cookie_status,
                "hasExternalApiKey": bool(os.getenv("OZON_ORD_API_KEY")),
                "hasApiToken": bool(os.getenv(API_TOKEN_ENV)),
                "defaultSheetUrlConfigured": bool(DEFAULT_SHEET_URL),
            }
        )

    def do_POST(self) -> None:
        if not self._authorize():
            return

        try:
            payload = self._read_json()
            if self.path == "/api/auth/ozon-cookie":
                self._handle_ozon_cookie(payload)
                return
            if self.path == "/api/sync/statistics":
                self._handle_statistics_sync(payload)
                return
            if self.path == "/api/sync/platforms":
                self._handle_platform_sync(payload)
                return
        except ValueError as error:
            self._send_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        except Exception as error:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
            return

        self._send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _authorize(self) -> bool:
        expected = os.getenv(API_TOKEN_ENV)
        header = self.headers.get("Authorization", "")
        if not expected or header != f"Bearer {expected}":
            self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized")
            return False
        return True

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON object payload is required")
        return data

    def _handle_ozon_cookie(self, payload: dict[str, Any]) -> None:
        cookie = str(payload.get("cookie") or "")
        base_url = str(payload.get("baseUrl") or "https://ord.ozon.ru")
        captured_at = payload.get("capturedAt")
        if captured_at is not None and not isinstance(captured_at, str):
            raise ValueError("capturedAt must be a string")

        stored = save_ozon_cookie(cookie, base_url, captured_at)
        self._send_json(
            {
                "ok": True,
                "cookieEntries": stored.cookie_entries,
                "updatedAt": stored.updated_at,
                "baseUrl": stored.base_url,
            }
        )

    def _handle_statistics_sync(self, payload: dict[str, Any]) -> None:
        apply_stored_ozon_cookie()
        sheet_url = str(payload.get("sheetUrl") or DEFAULT_SHEET_URL)
        dry_run = bool(payload.get("dryRun", False))
        result = run_statistics_sync(sheet_url, send=not dry_run)
        self._send_json(result.to_dict(), status=HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST)

    def _handle_platform_sync(self, payload: dict[str, Any]) -> None:
        sheet_url = str(payload.get("sheetUrl") or DEFAULT_SHEET_URL)
        sheet_name = str(payload.get("platformSheetName") or DEFAULT_PLATFORM_SHEET_NAME)
        dry_run = bool(payload.get("dryRun", False))
        result = run_platform_sync(sheet_url, sheet_name, send=not dry_run)
        self._send_json(result.to_dict(), status=HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)
