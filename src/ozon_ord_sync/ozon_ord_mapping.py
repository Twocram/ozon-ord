from __future__ import annotations

"""Compatibility wrapper for the legacy ozon_ord_mapping module."""

from ozon_ord_sync.application.formatting import (
    admin_statistic_payloads_to_json,
    payloads_to_json,
    platform_payloads_to_json,
    statistic_payloads_to_json,
)
from ozon_ord_sync.domain.mapping import (
    DEFAULT_CAMPAIGN_TYPE,
    DEFAULT_PLATFORM_TYPE,
    DEFAULT_VAT_RATE_LABEL,
    build_external_platform_id,
    build_external_statistic_id,
    build_platform_name,
    build_platform_payload,
    build_platform_sheet_payload,
    build_statistic_payload,
    format_decimal,
    map_row_to_ozon_ord_payload,
)

__all__ = [
    "DEFAULT_CAMPAIGN_TYPE",
    "DEFAULT_PLATFORM_TYPE",
    "DEFAULT_VAT_RATE_LABEL",
    "admin_statistic_payloads_to_json",
    "build_external_platform_id",
    "build_external_statistic_id",
    "build_platform_name",
    "build_platform_payload",
    "build_platform_sheet_payload",
    "build_statistic_payload",
    "format_decimal",
    "map_row_to_ozon_ord_payload",
    "payloads_to_json",
    "platform_payloads_to_json",
    "statistic_payloads_to_json",
]
