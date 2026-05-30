from __future__ import annotations

"""Compatibility wrapper for the legacy sync_service module."""

from ozon_ord_sync.application.sync_service import (
    PlatformErrorPayload,
    build_platform_error_payload,
    build_platform_error_rows,
    build_platform_sync_batch,
    build_sync_batch,
    extract_duplicate_statistic_row_numbers,
    extract_statistic_creation_errors,
    resolve_admin_statistics,
    resolve_creative_ids,
    resolve_platform_ids,
    save_platform_errors,
    split_resolution_errors,
    sync_batch,
    sync_batch_skipping_duplicate_statistics,
    sync_platform_batch,
)

__all__ = [
    "PlatformErrorPayload",
    "build_platform_error_payload",
    "build_platform_error_rows",
    "build_platform_sync_batch",
    "build_sync_batch",
    "extract_duplicate_statistic_row_numbers",
    "extract_statistic_creation_errors",
    "resolve_admin_statistics",
    "resolve_creative_ids",
    "resolve_platform_ids",
    "save_platform_errors",
    "split_resolution_errors",
    "sync_batch",
    "sync_batch_skipping_duplicate_statistics",
    "sync_platform_batch",
]
