from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class AppsScriptError(RuntimeError):
    pass


class AppsScriptClient:
    def __init__(self, web_app_url: str, token: str | None = None, timeout: int = 30):
        self.web_app_url = web_app_url
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "AppsScriptClient | None":
        web_app_url = os.getenv("GOOGLE_APPS_SCRIPT_WEB_APP_URL")
        if not web_app_url:
            return None

        token = os.getenv("GOOGLE_APPS_SCRIPT_TOKEN")
        timeout = int(os.getenv("GOOGLE_APPS_SCRIPT_TIMEOUT", "30"))
        return cls(web_app_url=web_app_url, token=token, timeout=timeout)

    def update_platform_errors(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": "update_platform_errors", "rows": rows}
        if self.token:
            payload["token"] = self.token

        request = urllib.request.Request(
            url=self.web_app_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            raise AppsScriptError(
                f"Apps Script request failed with HTTP {error.code}: {raw}"
            ) from error
        except urllib.error.URLError as error:
            raise AppsScriptError(f"Apps Script request failed: {error}") from error
