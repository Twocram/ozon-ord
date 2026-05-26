from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from typing import Any

from ozon_ord_sync.ozon_ord_mapping import (
    OzonOrdPlatformPayload,
    OzonOrdStatisticPayload,
)

DEFAULT_BASE_URL = "https://ord.ozon.ru"


class OzonOrdApiError(RuntimeError):
    pass


class ExternalOzonOrdClient:
    def __init__(
        self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 30
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "ExternalOzonOrdClient":
        api_key = os.getenv("OZON_ORD_API_KEY")
        if not api_key:
            raise OzonOrdApiError("Environment variable OZON_ORD_API_KEY is required")

        base_url = os.getenv("OZON_ORD_BASE_URL", DEFAULT_BASE_URL)
        timeout = int(os.getenv("OZON_ORD_TIMEOUT", "30"))
        return cls(api_key=api_key, base_url=base_url, timeout=timeout)

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

    @classmethod
    def from_env(cls) -> "AdminOzonOrdClient":
        cookie_header = os.getenv("OZON_ORD_COOKIE")
        if not cookie_header:
            raise OzonOrdApiError("Environment variable OZON_ORD_COOKIE is required")

        base_url = os.getenv("OZON_ORD_BASE_URL", DEFAULT_BASE_URL)
        timeout = int(os.getenv("OZON_ORD_TIMEOUT", "30"))
        app_name = os.getenv("OZON_ORD_APP_NAME", "ord-ui")
        app_version = os.getenv("OZON_ORD_APP_VERSION", "release/OORD-2732")
        return cls(
            cookie_header=cookie_header,
            base_url=base_url,
            timeout=timeout,
            app_name=app_name,
            app_version=app_version,
        )

    def add_statistics(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        body = {"statistics": payloads}
        endpoint = "/api/ord/admin/v6/statistic?__rr=1"
        url = f"{self.base_url}{endpoint}"
        request = urllib.request.Request(
            url=url,
            data=json.dumps(body, default=str).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ru",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15"
                ),
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/statistics/new",
                "Cookie": self.cookie_header,
                "X-O3-App-Name": self.app_name,
                "X-O3-App-Version": self.app_version,
            },
        )
        return _perform_json_request(request, timeout=self.timeout)


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
