from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from ozon_ord_sync.domain.models import OzonOrdPlatformPayload

DEFAULT_BASE_URL = "https://ord.ozon.ru"


class OzonOrdApiError(RuntimeError):
    pass


@dataclass
class CookieValidationResult:
    is_valid: bool | None
    status_code: int | None
    error: str | None = None


class ExternalOzonOrdClient:
    def __init__(
        self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 30
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def list_platforms(self, page_size: int = 1) -> dict[str, Any]:
        payload = {
            "cursor": {"externalId": "", "updatedAt": None},
            "orderBy": "ASC",
            "pageSize": page_size,
        }
        return self._request_json("POST", "/api/external/platform/list", payload)

    def register_or_update_platforms(
        self, payloads: list[OzonOrdPlatformPayload]
    ) -> dict[str, Any]:
        body = {"platforms": [asdict(payload) for payload in payloads]}
        return self._request_json("POST", "/api/external/v3/platform/batch", body)

    def get_platform_info(self, external_platform_id: str) -> dict[str, Any]:
        quoted = urllib.parse.quote(external_platform_id, safe="")
        return self._request_json("GET", f"/api/external/platform/{quoted}")

    def list_platforms_page(
        self,
        cursor_external_id: str = "",
        cursor_updated_at: dict[str, Any] | None = None,
        page_size: int = 2500,
    ) -> dict[str, Any]:
        payload = {
            "cursor": {
                "externalId": cursor_external_id,
                "updatedAt": cursor_updated_at,
            },
            "orderBy": "ASC",
            "pageSize": page_size,
        }
        return self._request_json("POST", "/api/external/platform/list", payload)

    def list_creatives(
        self,
        cursor_external_id: str = "",
        cursor_updated_at: dict[str, Any] | None = None,
        page_size: int = 2500,
    ) -> dict[str, Any]:
        payload = {
            "cursor": {
                "externalId": cursor_external_id,
                "updatedAt": cursor_updated_at,
            },
            "orderBy": "ASC",
            "pageSize": page_size,
        }
        return self._request_json("POST", "/api/external/creative/list", payload)

    def _request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        data = (
            None
            if payload is None
            else json.dumps(payload, default=str).encode("utf-8")
        )
        request = urllib.request.Request(
            url=url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        return _perform_json_request(request, timeout=self.timeout)


class AdminOzonOrdClient:
    def __init__(
        self,
        cookie_header: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 30,
        app_name: str = "ord-ui",
        app_version: str = "release/OORD-2732",
    ):
        self.cookie_header = cookie_header
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.app_name = app_name
        self.app_version = app_version

    def add_statistics(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        raw, status, url = self._post_statistics({"statistics": payloads})
        if 300 <= status < 400:
            raise OzonOrdApiError(
                "ORD redirected to login; cookie is invalid or expired"
            )
        if status >= 400:
            raise OzonOrdApiError(f"POST {url} failed with HTTP {status}: {raw}")
        return json.loads(raw) if raw else {}

    def validate_cookie(self) -> CookieValidationResult:
        try:
            raw, status, _ = self._post_statistics({"statistics": []})
        except OzonOrdApiError as error:
            return CookieValidationResult(is_valid=None, status_code=None, error=str(error))

        if status in {301, 302, 303, 307, 308, 401, 403}:
            return CookieValidationResult(
                is_valid=False,
                status_code=status,
                error=_response_error_text(raw)
                or "ORD redirected to login; cookie is invalid or expired",
            )

        if 200 <= status < 300 or status in {400, 405, 422}:
            return CookieValidationResult(is_valid=True, status_code=status)

        return CookieValidationResult(
            is_valid=None,
            status_code=status,
            error=_response_error_text(raw) or f"HTTP {status}",
        )

    def _post_statistics(self, body: dict[str, Any]) -> tuple[str, int, str]:
        # ponytail: ORD rejects urllib here; curl matches the browser request without adding deps.
        url = f"{self.base_url}/api/ord/admin/v6/statistic?__rr=1"
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                str(self.timeout),
                "--write-out",
                "\n%{http_code}",
                url,
                "-X",
                "POST",
                "-H",
                "accept: application/json, text/plain, */*",
                "-H",
                "accept-language: en-US,en;q=0.6",
                "-H",
                "cache-control: no-cache",
                "-H",
                "content-type: application/json",
                "-H",
                f"cookie: {self.cookie_header}",
                "-H",
                f"origin: {self.base_url}",
                "-H",
                "pragma: no-cache",
                "-H",
                f"referer: {self.base_url}/statistics/new",
                "-H",
                'sec-ch-ua: "Brave";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
                "-H",
                "sec-ch-ua-mobile: ?0",
                "-H",
                'sec-ch-ua-platform: "macOS"',
                "-H",
                "sec-fetch-dest: empty",
                "-H",
                "sec-fetch-mode: cors",
                "-H",
                "sec-fetch-site: same-origin",
                "-H",
                "sec-gpc: 1",
                "-H",
                "user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
                "-H",
                f"x-o3-app-name: {self.app_name}",
                "-H",
                f"x-o3-app-version: {self.app_version}",
                "--data-raw",
                json.dumps(body, default=str),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise OzonOrdApiError(result.stderr.strip() or "curl failed")

        raw, _, status = result.stdout.rpartition("\n")
        if not status.isdigit():
            raise OzonOrdApiError(f"POST {url} failed: missing HTTP status")
        return raw, int(status), url


def _response_error_text(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(payload, dict):
        for key in ("error", "message", "detail", "description"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return text


def _perform_json_request(
    request: urllib.request.Request, timeout: int
) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise OzonOrdApiError(
            f"{request.method} {request.full_url} failed with HTTP {error.code}: {raw}"
        ) from error
    except urllib.error.URLError as error:
        raise OzonOrdApiError(
            f"{request.method} {request.full_url} failed: {error}"
        ) from error
