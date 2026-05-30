from __future__ import annotations

import os

from ozon_ord_sync.infrastructure.apps_script import AppsScriptClient
from ozon_ord_sync.infrastructure.ozon_ord import (
    DEFAULT_BASE_URL,
    AdminOzonOrdClient,
    ExternalOzonOrdClient,
    OzonOrdApiError,
)


def build_external_ozon_ord_client_from_env() -> ExternalOzonOrdClient:
    api_key = os.getenv("OZON_ORD_API_KEY")
    if not api_key:
        raise OzonOrdApiError("Environment variable OZON_ORD_API_KEY is required")

    base_url = os.getenv("OZON_ORD_BASE_URL", DEFAULT_BASE_URL)
    timeout = int(os.getenv("OZON_ORD_TIMEOUT", "30"))
    return ExternalOzonOrdClient(api_key=api_key, base_url=base_url, timeout=timeout)


def build_admin_ozon_ord_client_from_env() -> AdminOzonOrdClient:
    cookie_header = os.getenv("OZON_ORD_COOKIE")
    if not cookie_header:
        raise OzonOrdApiError("Environment variable OZON_ORD_COOKIE is required")

    base_url = os.getenv("OZON_ORD_BASE_URL", DEFAULT_BASE_URL)
    timeout = int(os.getenv("OZON_ORD_TIMEOUT", "30"))
    app_name = os.getenv("OZON_ORD_APP_NAME", "ord-ui")
    app_version = os.getenv("OZON_ORD_APP_VERSION", "release/OORD-2732")
    return AdminOzonOrdClient(
        cookie_header=cookie_header,
        base_url=base_url,
        timeout=timeout,
        app_name=app_name,
        app_version=app_version,
    )


def build_apps_script_client_from_env() -> AppsScriptClient | None:
    web_app_url = os.getenv("GOOGLE_APPS_SCRIPT_WEB_APP_URL")
    if not web_app_url:
        return None

    token = os.getenv("GOOGLE_APPS_SCRIPT_TOKEN")
    timeout = int(os.getenv("GOOGLE_APPS_SCRIPT_TIMEOUT", "30"))
    return AppsScriptClient(web_app_url=web_app_url, token=token, timeout=timeout)
