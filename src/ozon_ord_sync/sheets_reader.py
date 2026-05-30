from __future__ import annotations

"""Compatibility wrapper for the legacy sheets_reader module."""

from ozon_ord_sync.application.sheet_parser import (
    TARGET_EXECUTOR,
    build_raw_row,
    filter_rows_for_processing,
    is_effectively_empty,
    normalize_header,
    parse_date,
    parse_decimal,
    parse_int,
    parse_platform_sheet,
    parse_sheet,
    rows_to_json,
    slugify,
    text_or_none,
    validate_platform_rows,
    validate_rows,
)
from ozon_ord_sync.infrastructure.google_sheets import (
    DEFAULT_PLATFORM_SHEET_NAME,
    DEFAULT_SHEET_URL,
    fetch_sheet_rows,
    google_sheet_csv_url,
)

__all__ = [
    "DEFAULT_PLATFORM_SHEET_NAME",
    "DEFAULT_SHEET_URL",
    "TARGET_EXECUTOR",
    "build_raw_row",
    "fetch_sheet_rows",
    "filter_rows_for_processing",
    "google_sheet_csv_url",
    "is_effectively_empty",
    "normalize_header",
    "parse_date",
    "parse_decimal",
    "parse_int",
    "parse_platform_sheet",
    "parse_sheet",
    "rows_to_json",
    "slugify",
    "text_or_none",
    "validate_platform_rows",
    "validate_rows",
]
