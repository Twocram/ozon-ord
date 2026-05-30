from __future__ import annotations

import csv
import re
import urllib.parse
import urllib.request
from io import StringIO

DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1PuvoA3GcHIger8bXYR0uY_jIhj_3LZ7ieypF1IcGcIw/edit?gid=0#gid=0"
)
DEFAULT_PLATFORM_SHEET_NAME = "Лист3"


def google_sheet_csv_url(
    sheet_url: str,
    gid: str | int | None = None,
    sheet_name: str | None = None,
) -> str:
    parsed = urllib.parse.urlparse(sheet_url)
    path_match = re.search(r"/spreadsheets/d/([^/]+)", parsed.path)
    if not path_match:
        raise ValueError("Unsupported Google Sheets URL format")

    sheet_id = path_match.group(1)
    if sheet_name is not None:
        return (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
            f"?tqx=out:csv&sheet={urllib.parse.quote(sheet_name)}"
        )

    fragment_params = urllib.parse.parse_qs(parsed.fragment)
    query_params = urllib.parse.parse_qs(parsed.query)
    resolved_gid = str(
        gid
        if gid is not None
        else fragment_params.get("gid", query_params.get("gid", ["0"]))[0]
    )

    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
        f"?format=csv&gid={resolved_gid}"
    )


def fetch_sheet_rows(
    sheet_url: str = DEFAULT_SHEET_URL,
    gid: str | int | None = None,
    sheet_name: str | None = None,
) -> tuple[list[str], list[list[str]]]:
    csv_url = google_sheet_csv_url(sheet_url, gid=gid, sheet_name=sheet_name)
    with urllib.request.urlopen(csv_url, timeout=30) as response:
        payload = response.read().decode("utf-8-sig")

    reader = csv.reader(StringIO(payload))
    rows = list(reader)
    if not rows:
        return [], []

    return rows[0], rows[1:]
