from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from ozon_ord_sync.application.sync_workflows import (
    run_platform_preview,
    run_platform_sync,
    run_statistics_preview,
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
from ozon_ord_sync.config.factories import build_admin_ozon_ord_client_from_env
from ozon_ord_sync.infrastructure.ozon_ord import OzonOrdApiError

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
        if self._path() != "/api/status":
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
                "hasAppsScript": bool(os.getenv("GOOGLE_APPS_SCRIPT_WEB_APP_URL")),
                "defaultSheetUrlConfigured": bool(DEFAULT_SHEET_URL),
                "defaultPlatformSheetName": DEFAULT_PLATFORM_SHEET_NAME,
            }
        )

    def do_POST(self) -> None:
        if not self._authorize():
            return

        try:
            payload = self._read_json()
            path = self._path()
            if path == "/api/auth/ozon-cookie":
                self._handle_ozon_cookie(payload)
                return
            if path == "/api/auth/validate":
                self._handle_auth_validate()
                return
            if path == "/api/preview/statistics":
                self._handle_statistics_preview(payload)
                return
            if path == "/api/preview/platforms":
                self._handle_platform_preview(payload)
                return
            if path == "/api/sync/statistics":
                self._handle_statistics_sync(payload)
                return
            if path == "/api/sync/platforms":
                self._handle_platform_sync(payload)
                return
        except ValueError as error:
            self._send_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        except OzonOrdApiError as error:
            self._send_error(HTTPStatus.BAD_GATEWAY, str(error))
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

    def _path(self) -> str:
        return urlsplit(self.path).path

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

    def _handle_auth_validate(self) -> None:
        apply_stored_ozon_cookie()
        cookie_status = stored_cookie_status()
        if not cookie_status["hasOzonCookie"]:
            self._send_json(
                {
                    "ok": False,
                    **cookie_status,
                    "cookieValid": None,
                    "validationError": "cookie is not set",
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        validation = build_admin_ozon_ord_client_from_env().validate_cookie()
        if validation.is_valid is True:
            self._send_json(
                {
                    "ok": True,
                    **cookie_status,
                    "cookieValid": True,
                    "validationStatusCode": validation.status_code,
                    "validationError": None,
                }
            )
            return

        status = (
            HTTPStatus.UNAUTHORIZED
            if validation.is_valid is False
            else HTTPStatus.BAD_GATEWAY
        )
        self._send_json(
            {
                "ok": False,
                **cookie_status,
                "cookieValid": validation.is_valid,
                "validationStatusCode": validation.status_code,
                "validationError": validation.error,
            },
            status=status,
        )

    def _handle_statistics_preview(self, payload: dict[str, Any]) -> None:
        result = run_statistics_preview(
            sheet_url=self._sheet_url(payload),
            limit=self._read_int(payload, "limit", default=3, minimum=0),
        )
        self._send_json(
            result.to_dict(),
            status=HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST,
        )

    def _handle_platform_preview(self, payload: dict[str, Any]) -> None:
        result = run_platform_preview(
            sheet_url=self._sheet_url(payload),
            sheet_name=self._platform_sheet_name(payload),
            limit=self._read_int(payload, "limit", default=3, minimum=0),
        )
        self._send_json(
            result.to_dict(),
            status=HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST,
        )

    def _handle_statistics_sync(self, payload: dict[str, Any]) -> None:
        apply_stored_ozon_cookie()
        result = run_statistics_sync(
            self._sheet_url(payload),
            send=not self._read_bool(payload, "dryRun", default=False),
        )
        self._send_json(
            result.to_dict(),
            status=HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST,
        )

    def _handle_platform_sync(self, payload: dict[str, Any]) -> None:
        result = run_platform_sync(
            self._sheet_url(payload),
            self._platform_sheet_name(payload),
            send=not self._read_bool(payload, "dryRun", default=False),
        )
        self._send_json(
            result.to_dict(),
            status=HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST,
        )

    def _sheet_url(self, payload: dict[str, Any]) -> str:
        return str(payload.get("sheetUrl") or DEFAULT_SHEET_URL)

    def _platform_sheet_name(self, payload: dict[str, Any]) -> str:
        return str(payload.get("platformSheetName") or DEFAULT_PLATFORM_SHEET_NAME)

    def _read_bool(
        self,
        payload: dict[str, Any],
        key: str,
        *,
        default: bool,
    ) -> bool:
        value = payload.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
        raise ValueError(f"{key} must be a boolean")

    def _read_int(
        self,
        payload: dict[str, Any],
        key: str,
        *,
        default: int,
        minimum: int | None = None,
    ) -> int:
        value = payload.get(key, default)
        if isinstance(value, bool):
            raise ValueError(f"{key} must be an integer")
        try:
            number = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{key} must be an integer") from error
        if minimum is not None and number < minimum:
            raise ValueError(f"{key} must be >= {minimum}")
        return number

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
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
