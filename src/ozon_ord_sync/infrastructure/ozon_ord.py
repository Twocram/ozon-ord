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
            message = _response_error_text(raw) or raw
            raise OzonOrdApiError(f"POST {url} failed with HTTP {status}: {message}")
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as error:
            raise OzonOrdApiError(
                "ORD returned non-JSON; cookie is invalid or expired"
            ) from error
        return loaded if isinstance(loaded, dict) else {}

    def list_contracts(self, query: dict[str, Any]) -> dict[str, Any]:
        return self._admin_request_json(
            "GET",
            f"/api/ord/admin/v6/contract/list?{admin_query(query)}",
            referer="/contracts",
        )

    def list_admin_creatives(self, query: dict[str, Any]) -> dict[str, Any]:
        return self._admin_request_json(
            "GET",
            f"/api/ord/admin/v4/creative/list?{admin_query(query)}",
            referer="/creatives",
        )

    def list_organisations(self, query: dict[str, Any]) -> dict[str, Any]:
        return self._admin_request_json(
            "GET",
            f"/api/ord/admin/v6/organisation/list?{admin_query(query)}",
            referer="/ad-providers",
        )

    def create_organisation(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Endpoint and referer mirror the browser "Добавление контрагента" request.
        return self._admin_request_json(
            "POST",
            "/api/ord/admin/v6/organisation",
            payload=payload,
            referer="/ad-providers/new",
        )

    def create_contract(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Endpoint and referer mirror the browser "Добавление договора" request.
        return self._admin_request_json(
            "POST",
            "/api/ord/admin/v6/contract",
            payload=payload,
            referer="/contracts/new",
        )

    def create_creative(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Endpoint and referer mirror the browser "Добавление креатива" request.
        return self._admin_request_json(
            "POST",
            "/api/ord/admin/v4/creative",
            payload=payload,
            referer="/creatives/new",
        )

    def upload_media(
        self,
        file_path: str,
        filename: str,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        # Mirrors the browser multipart upload to /api/ord/v2/file/media. The response
        # carries the stored file id/size that the creative payload references.
        form_value = f"file=@{file_path}"
        if content_type:
            form_value += f";type={content_type}"
        if filename:
            form_value += f";filename={filename}"

        url = f"{self.base_url}/api/ord/v2/file/media"
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--max-redirs",
            "5",
            "--max-time",
            str(self.timeout),
            "--cookie",
            self.cookie_header,
            "--cookie-jar",
            "/dev/null",
            "--write-out",
            "\n%{http_code}",
            url,
            "-X",
            "POST",
            "-H",
            "accept: application/json, text/plain, */*",
            "-H",
            "accept-language: ru",
            "-H",
            f"origin: {self.base_url}",
            "-H",
            f"referer: {self.base_url}/creatives/new",
            "-H",
            "user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "-H",
            f"x-o3-app-name: {self.app_name}",
            "-H",
            f"x-o3-app-version: {self.app_version}",
            "-F",
            form_value,
        ]

        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise OzonOrdApiError(result.stderr.strip() or "curl failed")

        raw, _, status = result.stdout.rpartition("\n")
        if not status.isdigit():
            raise OzonOrdApiError("media upload failed: missing HTTP status")
        status_code = int(status)
        if 300 <= status_code < 400:
            raise OzonOrdApiError(
                "ORD redirected to login; cookie is invalid or expired"
            )
        if status_code >= 400:
            message = _response_error_text(raw) or raw
            raise OzonOrdApiError(
                f"media upload failed with HTTP {status_code}: {message}"
            )
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as error:
            raise OzonOrdApiError("media upload returned non-JSON") from error
        return loaded if isinstance(loaded, dict) else {}

    def check_invoice_duplicates(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = invoice_duplicate_query(payload)
        return self._admin_request_json(
            "GET",
            f"/api/ord/admin/v5/invoice/duplicates?{query}",
            referer="/invoices/new?type=INVOICE_TYPE_INVOICE",
        )

    def create_extended_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._admin_request_json(
            "POST",
            "/api/ord/admin/v7/extended_invoice",
            payload=payload,
            referer="/invoices/new?type=INVOICE_TYPE_INVOICE",
        )

    def validate_cookie(self) -> CookieValidationResult:
        try:
            raw, status, _ = self._post_statistics({"statistics": []})
        except OzonOrdApiError as error:
            return CookieValidationResult(
                is_valid=None,
                status_code=None,
                error=str(error),
            )

        if status in {301, 302, 303, 307, 308}:
            return CookieValidationResult(
                is_valid=False,
                status_code=status,
                error="ORD redirected to login; cookie is invalid or expired",
            )

        if status in {401, 403}:
            return CookieValidationResult(
                is_valid=False,
                status_code=status,
                error=_response_error_text(raw) or f"HTTP {status}",
            )

        if 200 <= status < 300:
            if raw and not _is_json_response(raw):
                return CookieValidationResult(
                    is_valid=False,
                    status_code=status,
                    error="ORD returned non-JSON; cookie is invalid or expired",
                )
            return CookieValidationResult(is_valid=True, status_code=status)

        if status in {400, 405, 422}:
            return CookieValidationResult(is_valid=True, status_code=status)

        return CookieValidationResult(
            is_valid=None,
            status_code=status,
            error=_response_error_text(raw) or f"HTTP {status}",
        )

    def _admin_request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        referer: str = "/",
    ) -> dict[str, Any]:
        raw, status, url = self._curl_admin(method, endpoint, payload, referer)
        if 300 <= status < 400:
            raise OzonOrdApiError(
                "ORD redirected to login; cookie is invalid or expired"
            )
        if status >= 400:
            message = _response_error_text(raw) or raw
            raise OzonOrdApiError(
                f"{method} {url} failed with HTTP {status}: {message}"
            )
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as error:
            raise OzonOrdApiError(
                "ORD returned non-JSON; cookie is invalid or expired"
            ) from error
        return loaded if isinstance(loaded, dict) else {"items": loaded}

    def _post_statistics(self, body: dict[str, Any]) -> tuple[str, int, str]:
        # ponytail: ORD rejects urllib here; curl matches the browser request without adding deps.
        return self._curl_admin(
            "POST",
            "/api/ord/admin/v6/statistic?__rr=1",
            body,
            "/statistics/new",
        )

    def _curl_admin(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None,
        referer: str,
    ) -> tuple[str, int, str]:
        url = f"{self.base_url}{endpoint}"
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--max-redirs",
            "5",
            "--max-time",
            str(self.timeout),
            "--cookie",
            self.cookie_header,
            "--cookie-jar",
            "/dev/null",
            "--write-out",
            "\n%{http_code}",
            url,
            "-X",
            method,
            "-H",
            "accept: application/json, text/plain, */*",
            "-H",
            "accept-language: ru",
            "-H",
            "cache-control: no-cache",
            "-H",
            "content-type: application/json",
            "-H",
            f"origin: {self.base_url}",
            "-H",
            "pragma: no-cache",
            "-H",
            f"referer: {self.base_url}{referer}",
            "-H",
            "sec-fetch-dest: empty",
            "-H",
            "sec-fetch-mode: cors",
            "-H",
            "sec-fetch-site: same-origin",
            "-H",
            "user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "-H",
            f"x-o3-app-name: {self.app_name}",
            "-H",
            f"x-o3-app-version: {self.app_version}",
        ]
        if payload is not None:
            command += ["--data-raw", json.dumps(payload, default=str)]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise OzonOrdApiError(result.stderr.strip() or "curl failed")

        raw, _, status = result.stdout.rpartition("\n")
        if not status.isdigit():
            raise OzonOrdApiError(f"{method} {url} failed: missing HTTP status")
        return raw, int(status), url


def admin_query(query: dict[str, Any]) -> str:
    return urllib.parse.urlencode(
        [
            (key, _query_value(item))
            for key, value in query.items()
            if value is not None
            for item in (value if isinstance(value, list) else [value])
        ]
    )


def invoice_duplicate_query(payload: dict[str, Any]) -> str:
    service_price = payload.get("servicePrice") or {}
    fields = [
        ("key.invoiceNumber", payload.get("invoiceNumber")),
        ("key.invoiceDate", payload.get("invoiceDate")),
        ("key.startDate", payload.get("startDate")),
        ("key.endDate", payload.get("endDate")),
        ("key.clientRole", payload.get("clientRole")),
        ("key.contractId", payload.get("contractId")),
        ("key.contractorRole", payload.get("contractorRole")),
        ("key.servicePrice.amount", service_price.get("amount")),
        ("key.servicePrice.vatRate", service_price.get("vatRate")),
        ("key.servicePrice.excludingAmount", service_price.get("excludingAmount")),
        (
            "key.servicePrice.withNdsSelected",
            service_price.get("withNdsSelected"),
        ),
    ]
    return urllib.parse.urlencode(
        [(key, _query_value(value)) for key, value in fields if value is not None]
    )


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _is_json_response(raw: str) -> bool:
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        return False
    return True


def _response_error_text(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(payload, dict):
        challenge_url = payload.get("challengeURL")
        if isinstance(challenge_url, str) and challenge_url:
            return "Ozon anti-bot challenge required"
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
