from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DownloadedFile:
    path: Path
    content_type: str | None


def download_drive_file(url: str, target_dir: Path) -> DownloadedFile:
    file_id = google_drive_file_id(url)
    download_url = (
        f"https://drive.google.com/uc?export=download&id={file_id}" if file_id else url
    )
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        content_type = response.headers.get("content-type")
        suffix = _suffix_for_content_type(content_type)
        path = target_dir / f"{file_id or 'download'}{suffix}"
        path.write_bytes(response.read())
    return DownloadedFile(path=path, content_type=content_type)


def google_drive_file_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    match = re.search(r"/file/d/([^/]+)", parsed.path)
    if match:
        return match.group(1)
    query_id = urllib.parse.parse_qs(parsed.query).get("id")
    return query_id[0] if query_id else None


def _suffix_for_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    media_type = content_type.split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(media_type, "")
