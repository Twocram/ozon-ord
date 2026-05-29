from __future__ import annotations

"""Compatibility wrapper for the legacy ozon_ord_api module."""

from ozon_ord_sync.infrastructure.ozon_ord import (
    DEFAULT_BASE_URL,
    AdminOzonOrdClient,
    ExternalOzonOrdClient,
    OzonOrdApiError,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "AdminOzonOrdClient",
    "ExternalOzonOrdClient",
    "OzonOrdApiError",
]
