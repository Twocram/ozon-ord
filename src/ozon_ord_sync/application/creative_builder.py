from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from ozon_ord_sync.infrastructure.drive_files import download_drive_file
from ozon_ord_sync.infrastructure.ozon_ord import AdminOzonOrdClient

ADV_OBJECT_TYPE_TEXT_GRAPHIC_BLOCK = "ADV_OBJECT_TYPE_TEXT_GRAPHIC_BLOCK"
KKTU_CATEGORY_CODE = "6.1.1"
KKTU_CATEGORY_NAME = "Интернет-сервисы"


def upload_creative_media(
    admin_client: AdminOzonOrdClient,
    photo_url: str,
    target_dir: Path,
) -> dict[str, Any]:
    """Download the post photo from Drive, upload it to ORD, return the media ref.

    The temporary file lives under ``target_dir`` (caller owns cleanup, e.g. a
    TemporaryDirectory).
    """
    downloaded = download_drive_file(photo_url, target_dir)
    byte_size = downloaded.path.stat().st_size
    filename = downloaded.path.name
    response = admin_client.upload_media(
        str(downloaded.path),
        filename=filename,
        content_type=downloaded.content_type,
    )
    file_id, stored_size = _extract_media_ref(response)
    return {
        "id": file_id,
        "stored_size": stored_size,
        "byte_size": byte_size,
        "name": filename,
        "response": response,
    }


def build_creative_payload(
    raw_row: dict[str, Any],
    contract_id: str | None,
    media: dict[str, Any],
) -> dict[str, Any]:
    # Mirrors the browser "Добавление креатива" create-from-scratch body. ORD assigns
    # the marker/erid itself (marker is NOT sent on create), so it is read back from
    # the create response. "description" is intentionally left empty for now; the post
    # text is carried only as the creative's text material (textItems).
    text = raw_row.get("tekst_posta") or ""
    title = raw_row.get("nazvanie_kreativa") or ""
    urls = (raw_row.get("tselevye_ssylki_posta") or "").split()

    # The /file/media upload response returns only {id} (no size), so fall back to the
    # uploaded file's byte size — ORD needs a valid int64 for file.size.
    file_size = media.get("stored_size") or media.get("byte_size") or ""
    media_item = {
        "file": {"size": str(file_size), "id": media.get("id")},
        "errorFile": None,
        "isFocused": False,
        "text": "",
        "size": media.get("byte_size", 0),
        "loaded": media.get("byte_size", 0),
        "name": media.get("name") or "",
        "uuid": _uuid(),
    }
    text_item = {
        "file": {},
        "errorFile": None,
        "isFocused": False,
        "text": text,
        "size": 0,
        "loaded": 0,
        "name": "",
        "uuid": _uuid(),
    }
    url_list = [{"url": url, "uuid": _uuid()} for url in urls]

    return {
        "comment": "",
        "advObjectType": ADV_OBJECT_TYPE_TEXT_GRAPHIC_BLOCK,
        "kktuCategoryWeb": [{"code": KKTU_CATEGORY_CODE, "name": KKTU_CATEGORY_NAME}],
        "kktuCategory": [KKTU_CATEGORY_CODE],
        "description": "",
        "isPoliticAdv": False,
        "hasTargetLink": bool(url_list),
        "geo": [],
        "ageFrom": "",
        "ageTo": "",
        "sex": "",
        "mediaData": [media_item, text_item],
        "mediaItems": [media_item],
        "textItems": [text_item],
        "urlList": url_list,
        "isSocialAdv": False,
        "isSelfPromo": False,
        "title": title,
        "creativeTargeting": [],
        "cidIds": [],
        "contractIds": [contract_id] if contract_id else [],
    }


def _extract_media_ref(response: dict[str, Any]) -> tuple[str | None, str | None]:
    # Upload response references appear either at top level or nested under "file".
    for node in (response, response.get("file") if isinstance(response, dict) else None):
        if isinstance(node, dict):
            file_id = node.get("id") or node.get("fileId")
            size = node.get("size")
            if file_id is not None:
                return str(file_id), (str(size) if size is not None else None)
    return None, None


def _uuid() -> str:
    # Mirrors the browser's Math.random() client-side keys (server-side cosmetic).
    return str(random.random())
