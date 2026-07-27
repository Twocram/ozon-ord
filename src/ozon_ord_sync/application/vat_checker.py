"""VAT signals in contracts and acts/receipts.

VAT never keeps a row out of ORD — every row is registered either way. What it
decides is whether the row gets a note in the «Проверка» column:

* the contract or the act charges VAT (a rate above zero, "НДС включён", "в том
  числе НДС") -> register the row and mark it, a human confirms the amounts;
* the documents say VAT is not charged ("НДС не облагается", "Без НДС",
  "не является плательщиком НДС") or say nothing at all -> register, no mark.

When a document carries both kinds of wording the charged one wins: that is
exactly the ambiguous case a human should look at.
"""

from __future__ import annotations

import re
from decimal import Decimal

VAT_CHARGED = "vat_charged"
VAT_NOT_CHARGED = "vat_not_charged"

MANUAL_VAT_CHECK_TEXT = "Проверьте вручную"

_RATE_PATTERNS = (
    re.compile(r"ндс[^%\n]{0,40}?(\d{1,2}(?:[.,]\d+)?)\s*%"),
    re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:ндс|налог)"),
)
# "В том числе НДС" is also the header of a column whose value says "Без НДС", so
# the phrase only counts when nothing right after it cancels it.
_NOT_CHARGED_TAIL = r"без\s+ндс|не\s+облагается|0\s*%|0[.,]0{1,2}\b|[—–-]\s"
_CHARGED_RE = re.compile(
    r"ндс\s+включ[её]н|включая\s+ндс|с\s+уч[её]том\s+ндс|"
    r"сумма\s+с\s+ндс|цена\s+с\s+ндс|"
    rf"в\s+том\s+числе\s+ндс(?!\s*:?\s*(?:{_NOT_CHARGED_TAIL}))"
)
_NOT_CHARGED_RE = re.compile(
    r"без\s+ндс|без\s+налога\s*\(\s*ндс\s*\)|"
    r"ндс\s+не\s+(?:облагается|начисляется|предусмотрен\w*|включ[её]н\w*|выделяется|уплачивается)|"
    r"не\s+облагается\s+ндс|не\s+явля\w*\s+плательщик\w*\s+ндс|"
    r"освобожд\w*\s+от\s+(?:уплаты\s+)?ндс|ндс\s+отсутствует"
)


def detect_vat_status(text: str) -> str | None:
    """VAT_CHARGED, VAT_NOT_CHARGED, or None when the document is silent on VAT."""
    normalized = _normalize(text)
    rate = _rate(normalized)
    if (rate is not None and rate > 0) or _CHARGED_RE.search(normalized):
        return VAT_CHARGED
    if rate == 0 or _NOT_CHARGED_RE.search(normalized):
        return VAT_NOT_CHARGED
    return None


def vat_rate(text: str) -> Decimal | None:
    return _rate(_normalize(text))


def vat_check_note(
    contract_text: str,
    receipt_text: str,
    performer_status: str | None = None,
) -> str | None:
    """The «Проверка» note when VAT is charged anywhere, otherwise None."""
    if performer_status == "self_employed":
        return None

    parts = [
        f"в {label} {description}"
        for label, description in (
            ("договоре", _charge_description(contract_text)),
            ("акте/чеке", _charge_description(receipt_text)),
        )
        if description
    ]
    if not parts:
        return None
    return f"НДС: {', '.join(parts)}. {MANUAL_VAT_CHECK_TEXT}"


def _charge_description(text: str) -> str | None:
    if detect_vat_status(text) != VAT_CHARGED:
        return None
    rate = vat_rate(text)
    return f"ставка {_format_rate(rate)}%" if rate else "НДС включён"


def _format_rate(rate: Decimal) -> str:
    normalized = rate.normalize()
    return format(normalized, "f")


def _rate(normalized_text: str) -> Decimal | None:
    for pattern in _RATE_PATTERNS:
        match = pattern.search(normalized_text)
        if match:
            return Decimal(match.group(1).replace(",", "."))
    return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold())
