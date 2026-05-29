from __future__ import annotations

"""Compatibility wrapper for the legacy apps_script_client module."""

from ozon_ord_sync.infrastructure.apps_script import AppsScriptClient, AppsScriptError

__all__ = ["AppsScriptClient", "AppsScriptError"]
