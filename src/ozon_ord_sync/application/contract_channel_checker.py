from __future__ import annotations

import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ozon_ord_sync.application.contract_parser import parse_contract_text
from ozon_ord_sync.application.receipt_parser import (
    document_type_error,
    parse_receipt_text,
    self_employed_receipt_number_error,
)
from ozon_ord_sync.application.sheet_parser import parse_document_check_sheet
from ozon_ord_sync.application.vat_checker import vat_check_note
from ozon_ord_sync.infrastructure.document_text import extract_document_text
from ozon_ord_sync.infrastructure.drive_files import download_drive_file

MANUAL_CHECK_TEXT = "Проверьте вручную"


@dataclass
class ContractChannelCheckRow:
    row_number: int
    value: str
    reason: str
    telegram_links: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_contract_channel_check_rows(sheet_url: str) -> list[ContractChannelCheckRow]:
    _, rows = parse_document_check_sheet(sheet_url)
    results: list[ContractChannelCheckRow] = []
    with tempfile.TemporaryDirectory() as tmp:
        target_dir = Path(tmp)
        for row in rows:
            if row.contract_url is None:
                continue
            try:
                downloaded = download_drive_file(row.contract_url, target_dir)
                text = extract_document_text(downloaded.path, downloaded.content_type)
            except Exception as error:
                results.append(
                    ContractChannelCheckRow(
                        row_number=row.row_number,
                        value=f"Ошибка проверки договора: {error}",
                        reason="contract read failed",
                        telegram_links=[],
                    )
                )
                continue

            contract = parse_contract_text(text)
            service_table = extract_service_table_text(text)
            links = extract_telegram_links(service_table)
            has_authors = mentions_telegram_authors(service_table)
            messages: list[str] = []
            reasons: list[str] = []

            if len(links) > 1 or has_authors:
                messages.append(MANUAL_CHECK_TEXT)
                reasons.append(
                    "multiple telegram links"
                    if len(links) > 1
                    else "telegram channel authors mentioned"
                )

            if row.receipts_acts_url:
                try:
                    receipt_file = download_drive_file(row.receipts_acts_url, target_dir)
                    receipt_text = extract_document_text(
                        receipt_file.path,
                        receipt_file.content_type,
                    )
                    receipt = parse_receipt_text(receipt_text, row.receipts_acts_url)
                    mismatch = document_type_error(
                        contract.performer_status,
                        receipt.document_type,
                    )
                    if mismatch:
                        messages.append(mismatch)
                        reasons.append("contract/receipt document type mismatch")

                    number_error = self_employed_receipt_number_error(
                        contract.performer_status,
                        receipt.document_type,
                        receipt.receipt_number,
                    )
                    if number_error:
                        messages.append(number_error)
                        reasons.append("invalid self-employed receipt number")

                    # VAT does not fail a row — it only asks for a human look.
                    vat_note = vat_check_note(
                        contract.text,
                        receipt.text,
                        contract.performer_status,
                    )
                    if vat_note:
                        messages.append(vat_note)
                        reasons.append("VAT charged in contract or act")
                except Exception as error:
                    messages.append(f"Ошибка проверки файла «Чеки/Акты»: {error}")
                    reasons.append("receipt read failed")

            if messages:
                results.append(
                    ContractChannelCheckRow(
                        row_number=row.row_number,
                        value="\n".join(messages),
                        reason=", ".join(reasons),
                        telegram_links=links,
                    )
                )
    return results


def extract_service_table_text(text: str) -> str:
    start = re.search(
        r"исполнитель\s+оказывает\s+заказчику\s+следующие\s+рекламные\s+услуги",
        text,
        flags=re.IGNORECASE,
    )
    if not start:
        return ""

    remainder = text[start.end() :]
    end = re.search(
        r"(?:\bИТОГО\s*:|\bПо\s+согласованию\s+(?:Сторон|с\s+Заказчиком)|\n\s*2\.)",
        remainder,
        flags=re.IGNORECASE,
    )
    return remainder[: end.start()] if end else remainder


def extract_telegram_links(text: str) -> list[str]:
    compact = re.sub(r"https?://t\.me\s*/\s*", "https://t.me/", text, flags=re.I)
    links = []
    for username in re.findall(r"(?:https?://)?t\.me/([a-zA-Z0-9_]+)", compact):
        link = f"https://t.me/{username}"
        if link not in links:
            links.append(link)
    return links


def mentions_telegram_authors(text: str) -> bool:
    return bool(
        re.search(
            r"телеграмм?\s+канал(?:е|а|ах)\s+авторов",
            text,
            flags=re.IGNORECASE,
        )
    )
