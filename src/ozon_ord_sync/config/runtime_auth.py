from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_AUTH_PATH = Path(".runtime/ozon-cookie.json")


@dataclass
class StoredOzonCookie:
    base_url: str
    cookie: str
    captured_at: str | None
    updated_at: str

    @property
    def cookie_entries(self) -> int:
        return sum(1 for part in self.cookie.split(";") if part.strip())


def save_ozon_cookie(
    cookie: str,
    base_url: str,
    captured_at: str | None = None,
    path: Path = DEFAULT_AUTH_PATH,
) -> StoredOzonCookie:
    cookie = cookie.strip()
    if not cookie:
        raise ValueError("cookie is required")

    stored = StoredOzonCookie(
        base_url=base_url.rstrip("/") or "https://ord.ozon.ru",
        cookie=cookie,
        captured_at=captured_at,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    os.environ["OZON_ORD_COOKIE"] = stored.cookie
    os.environ["OZON_ORD_BASE_URL"] = stored.base_url
    return stored


def load_ozon_cookie(path: Path = DEFAULT_AUTH_PATH) -> StoredOzonCookie | None:
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    return StoredOzonCookie(
        base_url=str(data.get("base_url") or "https://ord.ozon.ru").rstrip("/"),
        cookie=str(data.get("cookie") or ""),
        captured_at=data.get("captured_at"),
        updated_at=str(data.get("updated_at") or ""),
    )


def apply_stored_ozon_cookie(path: Path = DEFAULT_AUTH_PATH) -> StoredOzonCookie | None:
    stored = load_ozon_cookie(path)
    if stored is None or not stored.cookie:
        return None

    os.environ["OZON_ORD_COOKIE"] = stored.cookie
    os.environ["OZON_ORD_BASE_URL"] = stored.base_url
    return stored


def stored_cookie_status(path: Path = DEFAULT_AUTH_PATH) -> dict[str, Any]:
    stored = load_ozon_cookie(path)
    if stored is None or not stored.cookie:
        return {
            "hasOzonCookie": False,
            "cookieEntries": 0,
            "cookieUpdatedAt": None,
            "baseUrl": None,
        }

    return {
        "hasOzonCookie": True,
        "cookieEntries": stored.cookie_entries,
        "cookieUpdatedAt": stored.updated_at,
        "baseUrl": stored.base_url,
    }
