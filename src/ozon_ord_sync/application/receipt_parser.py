from __future__ import annotations

import re
import tempfile
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import islice
from pathlib import Path
from typing import Any

from ozon_ord_sync.application.name_matching import is_noise_word
from ozon_ord_sync.application.sheet_parser import (
    parse_decimal,
    parse_document_check_sheet,
)
from ozon_ord_sync.infrastructure.document_text import extract_document_text
from ozon_ord_sync.infrastructure.drive_files import download_drive_file
from ozon_ord_sync.infrastructure.lknpd import receipt_exists

DOCUMENT_TYPE_ACT = "act"
DOCUMENT_TYPE_RECEIPT = "receipt"

CONFIDENCE_HIGH = "high"
CONFIDENCE_LOW = "low"

# ФИО shapes, best first. Latin letters are allowed inside the word classes
# because OCR mixes alphabets ("ДОРОФEEВА" with Latin E) — `name_matching`
# repairs those homoglyphs before comparing.
_SCORE_FULL_NAME = 4  # Дорофеева Алиса Михайловна
_SCORE_SURNAME_INITIALS = 3  # Иванов И. И.
_SCORE_THREE_WORDS = 2  # three capitalised words, no patronymic
_SCORE_TWO_WORDS = 1  # Иванов Иван / Иванов И.

_WORD = r"[А-ЯЁA-Z](?:[а-яёa-z]+|[А-ЯЁA-Z]+)?\.?"
_WORD_UNIT_RE = re.compile(rf"{_WORD}(?:-{_WORD})?")
_PATRONYMIC_RE = re.compile(
    r"(?:ович|евич|ьич|иевич|овна|евна|ична|инична|кызы|оглы|улы)\.?$",
    re.IGNORECASE,
)
# ЛК НПД receipt ids are exactly ten lowercase Latin/digit characters
# ("2008miu7nc"). OCR reads some of them as Cyrillic look-alikes.
_LKNPD_ID_LENGTH = 10
_LKNPD_RECEIPT_ID_RE = re.compile(r"/receipt/\d{10,12}/([0-9a-z]+)", re.IGNORECASE)
# Character pairs OCR mixes up inside a receipt id. Unlike the Cyrillic
# look-alikes above these are ambiguous in both directions ("6" and "b" are both
# valid characters of an id), so they are resolved by asking ЛК НПД.
_CONFUSABLE = {
    "0": "o",
    "o": "0",
    "1": "li",
    "l": "1i",
    "i": "1l",
    "2": "z",
    "z": "2",
    "4": "a",
    "a": "4",
    "5": "s",
    "s": "5",
    "6": "b",
    "b": "68",
    "8": "b",
    "7": "t",
    "t": "7",
    "9": "gq",
    "g": "9q",
    "q": "9g",
    "u": "v",
    "v": "u",
    "n": "h",
    "h": "n",
    "c": "e",
    "e": "c",
}

_ID_HOMOGLYPHS = {
    "а": "a",
    "б": "6",
    "в": "b",
    "г": "r",
    "е": "e",
    "з": "3",
    "и": "u",
    "й": "u",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "п": "n",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
}

_MONTHS_GENITIVE = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

# The title of a УПД and of the счёт-фактура printed on the same form. Declined
# forms ("к счету-фактуре") are matched too but carry no number of their own, so
# they are skipped when the number is read.
_TRANSFER_DOCUMENT_RE = re.compile(
    r"сч[её]т\w*[-\s]фактур\w*|универсальн\w*\s+передаточн\w*\s+документ\w*",
    re.IGNORECASE,
)

_SURNAME_ENDING_RE = re.compile(
    r"(?:ов|ев|ёв|ин|ын|ова|ева|ёва|ина|ына|ский|ская|цкий|цкая|ской|"
    r"ко|енко|юк|чук|ян|швили|дзе|ич|овна|евна|ична)\.?$",
    re.IGNORECASE,
)
_PERFORMER_LABEL_RE = re.compile(
    r"\b(?:исполнител|продав|самозанят|налогоплательщик|получатель\s+платеж|режим\s+н)",
    re.IGNORECASE,
)
_CUSTOMER_LABEL_RE = re.compile(
    r"\b(?:заказчик|покупател|плательщик|директор|бухгалтер)",
    re.IGNORECASE,
)


@dataclass
class ReceiptInfo:
    document_type: str | None
    receipt_number: str | None
    issued_at: datetime | None
    seller_name: str | None
    total_amount: Decimal | None
    inns: list[str]
    text: str
    seller_name_confidence: str | None = None
    receipt_number_verified: bool | None = None


@dataclass
class DocumentCheckReceiptRow:
    row_number: int
    counterparty: str | None
    payment_amount: Decimal | None
    receipts_acts_url: str | None
    content_type: str | None
    receipt: ReceiptInfo | None
    amount_matches: bool | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_receipts_from_sheet(sheet_url: str) -> list[DocumentCheckReceiptRow]:
    _, rows = parse_document_check_sheet(sheet_url)
    results: list[DocumentCheckReceiptRow] = []
    with tempfile.TemporaryDirectory() as tmp:
        target_dir = Path(tmp)
        for row in rows:
            if row.receipts_acts_url is None:
                results.append(
                    DocumentCheckReceiptRow(
                        row.row_number,
                        row.counterparty,
                        row.payment_amount,
                        None,
                        None,
                        None,
                        None,
                        "missing Чеки/Акты link",
                    )
                )
                continue

            try:
                downloaded = download_drive_file(row.receipts_acts_url, target_dir)
                text = extract_document_text(downloaded.path, downloaded.content_type)
                receipt = verify_receipt_number(
                    parse_receipt_text(text, row.receipts_acts_url)
                )
                results.append(
                    DocumentCheckReceiptRow(
                        row.row_number,
                        row.counterparty,
                        row.payment_amount,
                        row.receipts_acts_url,
                        downloaded.content_type,
                        receipt,
                        row.payment_amount == receipt.total_amount,
                    )
                )
            except Exception as error:
                results.append(
                    DocumentCheckReceiptRow(
                        row.row_number,
                        row.counterparty,
                        row.payment_amount,
                        row.receipts_acts_url,
                        None,
                        None,
                        None,
                        str(error),
                    )
                )
    return results


def parse_receipt_text(text: str, source_url: str | None = None) -> ReceiptInfo:
    document_type = _parse_document_type(text, source_url)
    # A УПД states its number and date on one line somewhere in the form, far from
    # the heading, and that line is more trustworthy than a scan of the first lines
    # (which in a УПД is full of "от 26 декабря 2011 г. № 1137" boilerplate). It is
    # only consulted when the heading names no document of its own, so an ordinary
    # act that merely refers to a счёт-фактура keeps its own number and date.
    heading_number = _parse_document_number(text, source_url, document_type)
    transfer_number, transfer_date = (
        (None, None) if heading_number else _parse_transfer_document(text)
    )
    receipt_number = heading_number or transfer_number
    is_lknpd = _is_lknpd_url(source_url)
    issued_at = (
        (_parse_lknpd_datetime(text) if is_lknpd else None)
        or _parse_receipt_datetime(text)
        or transfer_date
        or _parse_act_date(text)
    )
    seller_name, seller_name_confidence = extract_person_name(text)
    total_amount = _parse_total_amount(text)
    inns = re.findall(r"(?<!\d)\d{10,12}(?!\d)", text.replace(" ", ""))

    return ReceiptInfo(
        document_type=document_type,
        receipt_number=receipt_number,
        issued_at=issued_at,
        seller_name=seller_name,
        total_amount=total_amount,
        inns=inns,
        text=text,
        seller_name_confidence=seller_name_confidence,
    )


def self_employed_receipt_number_is_valid(
    performer_status: str | None,
    document_type: str | None,
    receipt_number: str | None,
) -> bool | None:
    if performer_status != "self_employed":
        return None
    if document_type != DOCUMENT_TYPE_RECEIPT or not receipt_number:
        return False
    return any(char.isalpha() for char in receipt_number) and any(
        char.isdigit() for char in receipt_number
    )


def self_employed_receipt_number_error(
    performer_status: str | None,
    document_type: str | None,
    receipt_number: str | None,
) -> str | None:
    if (
        self_employed_receipt_number_is_valid(
            performer_status,
            document_type,
            receipt_number,
        )
        is False
    ):
        return "Ошибка: номер чека самозанятого должен содержать буквы и цифры"
    return None


def document_type_matches(
    performer_status: str | None,
    document_type: str | None,
) -> bool | None:
    expected = {
        "self_employed": DOCUMENT_TYPE_RECEIPT,
        "entrepreneur": DOCUMENT_TYPE_ACT,
    }.get(performer_status)
    if expected is None or document_type is None:
        return None
    return document_type == expected


def document_type_error(
    performer_status: str | None,
    document_type: str | None,
) -> str | None:
    if document_type_matches(performer_status, document_type) is not False:
        return None
    if performer_status == "self_employed":
        return "Ошибка: для самозанятого в «Чеки/Акты» должен быть чек"
    return "Ошибка: для ИП в «Чеки/Акты» должен быть акт"


def _parse_document_type(text: str, source_url: str | None) -> str | None:
    if _is_lknpd_url(source_url):
        return DOCUMENT_TYPE_RECEIPT
    heading = _document_heading(text).casefold()
    if re.match(r"\s*чек\b", heading):
        return DOCUMENT_TYPE_RECEIPT
    if re.match(r"\s*акт\b", heading):
        return DOCUMENT_TYPE_ACT
    # A УПД is an act too — it just carries the счёт-фактура on the same form, and
    # its heading is the three-word title "Универсальный передаточный документ".
    if _TRANSFER_DOCUMENT_RE.search(text):
        return DOCUMENT_TYPE_ACT
    return None


def _parse_transfer_document(text: str) -> tuple[str | None, datetime | None]:
    """Number and date of a УПД / счёт-фактура, taken from the line that states both."""
    for line in text.splitlines():
        anchor = _TRANSFER_DOCUMENT_RE.search(line)
        if not anchor:
            continue
        tail = line[anchor.end() :]
        match = re.search(r"(?:№|N[ºo°]?|номер)\s*([^\s,;]+)", tail)
        # Blank fields of the form are printed as "№ -- от --".
        if not match or not re.search(r"[0-9a-zа-яё]", match.group(1), flags=re.I):
            continue
        return match.group(1).rstrip(".;"), _parse_date_phrase(tail[match.end() :])
    return None, None


def _parse_date_phrase(value: str) -> datetime | None:
    match = re.search(r"от\s+(\d{1,2})\s+([а-яё]+)\s+(\d{4})", value, flags=re.IGNORECASE)
    if match:
        month = _MONTHS_GENITIVE.get(match.group(2).casefold())
        if month is not None:
            return datetime(int(match.group(3)), month, int(match.group(1)))

    match = re.search(r"от\s+(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", value)
    if match:
        day, month, year = map(int, match.groups())
        return datetime(year + 2000 if year < 100 else year, month, day)
    return None


def _parse_document_number(
    text: str,
    source_url: str | None = None,
    document_type: str | None = None,
) -> str | None:
    # A ЛК НПД link carries the receipt id in its path, which beats any reading of
    # the document: OCR turns "200v1ohcgi" into "200vlohcgi" and PDF layout splits
    # "2008miu7nc" into "2008miu7 nc".
    receipt_id = lknpd_receipt_id(source_url)
    if receipt_id:
        return receipt_id

    heading = _document_heading(text)
    match = re.search(
        r"\b(?:чек|акт)\b[^\n]{0,120}?(?:№|N[ºo°]?|номер)\s*([^\s,]+)",
        heading,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    number = match.group(1).rstrip(".;")
    if document_type != DOCUMENT_TYPE_RECEIPT:
        # Act numbers are written by hand and may legitimately be Cyrillic ("15-РК").
        return number
    return _repair_document_number(
        _join_split_receipt_id(number, heading[match.end(1) :], document_type)
    )


def verify_receipt_number(receipt: ReceiptInfo) -> ReceiptInfo:
    """Confirm a self-employed receipt number against ЛК НПД, fixing OCR misreads.

    Sets `receipt_number_verified`: True when ЛК НПД knows the number (possibly
    after correcting it), False when it knows neither the number as read nor any
    near reading of it, and None when there was nothing to check against — an act,
    an id of another shape, no ИНН in the document, or ЛК НПД being unreachable.
    """
    inn = self_employed_inn(receipt)
    if (
        receipt.document_type != DOCUMENT_TYPE_RECEIPT
        or not is_lknpd_receipt_id(receipt.receipt_number)
        or inn is None
    ):
        return receipt

    confirmed, answered = resolve_receipt_id(inn, receipt.receipt_number.casefold())
    if confirmed:
        receipt.receipt_number = confirmed
        receipt.receipt_number_verified = True
    elif answered:
        receipt.receipt_number_verified = False
    return receipt


def self_employed_inn(receipt: ReceiptInfo) -> str | None:
    """The 12-digit ИНН of the self-employed seller (the customer's is 10-digit)."""
    return next((inn for inn in receipt.inns if len(inn) == 12), None)


def resolve_receipt_id(
    inn: str,
    receipt_id: str,
    exists: Callable[[str, str], bool | None] | None = None,
    max_probes: int = 24,
) -> tuple[str | None, bool]:
    """The reading ЛК НПД confirms, and whether ЛК НПД answered at all.

    OCR reads "204qno6rie" as "204qnobrie" and nothing local can tell which is
    right, so ask ЛК НПД: first about the id as read, then about the readings one
    and two confusable characters away.
    """
    probe = exists or receipt_exists
    for candidate in islice(receipt_id_candidates(receipt_id), max_probes):
        verdict = probe(inn, candidate)
        if verdict is None:
            return None, False  # unreachable: keep whatever was read
        if verdict:
            return candidate, True
    return None, True


def receipt_id_candidates(receipt_id: str) -> Iterator[str]:
    """The id as read, then readings with one and two characters swapped."""
    seen = {receipt_id}
    yield receipt_id
    for distance in (1, 2):
        for candidate in _swapped(receipt_id, distance):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate


def _swapped(value: str, distance: int) -> Iterator[str]:
    if distance == 0:
        yield value
        return
    for index, char in enumerate(value):
        for replacement in _CONFUSABLE.get(char, ""):
            head = value[:index] + replacement
            for tail in _swapped(value[index + 1 :], distance - 1):
                yield head + tail


def is_lknpd_receipt_id(value: str | None) -> bool:
    return bool(value) and bool(
        re.fullmatch(rf"[0-9a-z]{{{_LKNPD_ID_LENGTH}}}", value, flags=re.IGNORECASE)
    )


def lknpd_receipt_id(url: str | None) -> str | None:
    """Receipt id from a ЛК НПД print link: /api/v1/receipt/<ИНН>/<id>/print."""
    if not _is_lknpd_url(url):
        return None
    match = _LKNPD_RECEIPT_ID_RE.search(urllib.parse.urlparse(url).path)
    return match.group(1) if match else None


def _repair_document_number(number: str) -> str:
    """Turn Cyrillic look-alikes back into the Latin characters of a receipt id."""
    if not any(char in _ID_HOMOGLYPHS for char in number.casefold()):
        return number
    # Only ids that already mix alphabets are OCR damage; "б/н" stays as it is.
    if not any(char.isdigit() or "a" <= char.casefold() <= "z" for char in number):
        return number
    return "".join(_ID_HOMOGLYPHS.get(char.casefold(), char) for char in number)


def _join_split_receipt_id(number: str, tail: str, document_type: str | None) -> str:
    """Reattach the parts of a ЛК НПД id that the PDF layout split apart.

    Only for чеки, and only when the fragments add up to exactly one id
    ("Чек Nº204 qnobrie" -> "204qnobrie"); act numbers are left as they are and a
    heading that merely continues with words ("Акт № 24 от 30 апреля") never adds
    up to a ten-character id.
    """
    if document_type != DOCUMENT_TYPE_RECEIPT or len(number) >= _LKNPD_ID_LENGTH:
        return number

    joined = number
    rest = tail
    while len(joined) < _LKNPD_ID_LENGTH:
        match = re.match(r"\s+([0-9a-zа-яё]{1,9})(?![0-9a-zа-яё])", rest, flags=re.IGNORECASE)
        if not match:
            return number
        joined += match.group(1)
        rest = rest[match.end() :]

    if len(joined) != _LKNPD_ID_LENGTH:
        return number
    return joined if _is_receipt_id(_repair_document_number(joined)) else number


def _is_receipt_id(value: str) -> bool:
    return bool(re.fullmatch(r"(?=.*\d)(?=.*[a-z])[0-9a-z]+", value, flags=re.IGNORECASE))


def _document_heading(text: str) -> str:
    return "\n".join(line for line in text.splitlines()[:4] if line.strip())


def _parse_receipt_datetime(text: str) -> datetime | None:
    match = re.search(r"\b\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}\b", text)
    if not match:
        return None
    return datetime.strptime(match.group(0), "%d.%m.%Y %H:%M:%S")


def _parse_lknpd_datetime(text: str) -> datetime | None:
    match = re.search(
        r"\b(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2})(?::\d{2})?(?:\([^)]*\))?",
        text,
    )
    if not match:
        return None
    fmt = "%d.%m.%y %H:%M" if len(match.group(1).rsplit(".", 1)[-1]) == 2 else "%d.%m.%Y %H:%M"
    return datetime.strptime(f"{match.group(1)} {match.group(2)}", fmt)


def _parse_act_date(text: str) -> datetime | None:
    heading = _document_heading(text)
    # "от 30 апреля 2026 г." and the contract-style "г. Москва «8» июля 2026 года".
    # The month name has to be a real one, so scan until one matches.
    for match in re.finditer(
        r"«?(\d{1,2})»?\s+([а-яё]+)\s+(\d{4})",
        heading,
        flags=re.IGNORECASE,
    ):
        month = _MONTHS_GENITIVE.get(match.group(2).casefold())
        if month is not None:
            return datetime.combine(
                date(int(match.group(3)), month, int(match.group(1))),
                datetime.min.time(),
            )

    numeric = re.search(
        r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b",
        heading,
    )
    if numeric:
        day, month, year = map(int, numeric.groups())
        year += 2000 if year < 100 else 0
        return datetime(year, month, day)

    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", heading)
    if iso:
        year, month, day = map(int, iso.groups())
        return datetime(year, month, day)
    return None


def extract_person_name(text: str) -> tuple[str | None, str | None]:
    """Best ФИО found in a «Чеки/Акты» document, plus how confident the guess is.

    Chasing a fixed layout ("the line after «Режим НО»") breaks as soon as OCR
    reorders the page or the file is an ИП act instead of a self-employed
    receipt. Instead, collect every run of capitalised words that is not broken
    up by punctuation or by a label word, score the runs by how much they look
    like a ФИО, and prefer runs that sit under a performer label ("Исполнитель",
    "Продавец") over ones under a customer label ("Заказчик", "директор").

    Confidence is `high` for a real ФИО shape (ФИО with a patronymic, or surname
    plus initials) or for anything under a performer label, and `low` for looser
    guesses — callers downgrade failed checks on low-confidence names instead of
    blocking the row.
    """
    candidates: list[tuple[int, int, str]] = []
    for group in _word_groups(text):
        candidates.extend(_name_candidates(group))
    if not candidates:
        return None, None

    labels = _label_positions(text)
    score, position, name = max(
        candidates,
        key=lambda item: (_label_bucket(labels, item[1]), item[0], -item[1]),
    )
    bucket = _label_bucket(labels, position)
    confidence = (
        CONFIDENCE_HIGH if score >= _SCORE_SURNAME_INITIALS or bucket > 0 else CONFIDENCE_LOW
    )
    return re.sub(r"\s+", " ", name).strip(" ,"), confidence


def _word_groups(text: str) -> list[list[tuple[int, str]]]:
    """Runs of capitalised words separated only by whitespace, split on noise words."""
    groups: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    previous_end: int | None = None
    for match in _WORD_UNIT_RE.finditer(text):
        separated = (
            previous_end is not None and text[previous_end : match.start()].strip() != ""
        )
        if current and separated:
            groups.append(current)
            current = []
        previous_end = match.end()
        if is_noise_word(match.group(0)):
            if current:
                groups.append(current)
                current = []
            continue
        current.append((match.start(), match.group(0)))
    if current:
        groups.append(current)
    return groups


def _name_candidates(group: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    candidates: list[tuple[int, int, str]] = []
    for size in (3, 2):
        for index in range(len(group) - size + 1):
            window = group[index : index + size]
            words = [word for _, word in window]
            score = _name_shape_score(words)
            if not score:
                continue
            # Weak shapes are just capitalised words in a row ("ОКАЗАНО НА
            # СУММУ" in an ALL CAPS scan): keep them only when one word carries a
            # Russian surname/patronymic ending.
            if score < _SCORE_SURNAME_INITIALS and not any(
                _SURNAME_ENDING_RE.search(word) for word in words
            ):
                continue
            candidates.append((score, window[0][0], " ".join(words)))
    return candidates


def _name_shape_score(words: list[str]) -> int:
    initials = [word for word in words if _is_initial(word)]
    if len(words) == 3:
        if not initials and _PATRONYMIC_RE.search(words[2]):
            return _SCORE_FULL_NAME
        if len(initials) == 2 and not _is_initial(words[0]):
            return _SCORE_SURNAME_INITIALS
        if not initials:
            return _SCORE_THREE_WORDS
        return 0
    if _is_initial(words[0]):
        return 0
    return _SCORE_TWO_WORDS if len(initials) <= 1 else 0


def _is_initial(word: str) -> bool:
    return len(word.rstrip(".")) == 1


def _label_positions(text: str) -> list[tuple[int, int]]:
    positions = [(match.start(), 1) for match in _PERFORMER_LABEL_RE.finditer(text)]
    positions += [(match.start(), -1) for match in _CUSTOMER_LABEL_RE.finditer(text)]
    return sorted(positions)


def _label_bucket(labels: list[tuple[int, int]], position: int) -> int:
    preceding = [kind for start, kind in labels if start < position]
    return preceding[-1] if preceding else 0


def _parse_total_amount(text: str) -> Decimal | None:
    patterns = [
        r"(?:Итого к оплате|того к оплате|Всего оказано услуг на сумму)[:\s]*([\d\s\xa0]+[,.]\d{2})",
        r"([\d\s\xa0]+[,.]\d{2})\s*(?:₽|руб\.?)",
    ]
    for pattern in patterns:
        amounts = re.findall(pattern, text, flags=re.IGNORECASE)
        if amounts:
            return parse_decimal(amounts[-1].replace("₽", "").replace("руб.", ""))
    return None


def _first_match(pattern: str, text: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1) if match else None


def _is_lknpd_url(url: str | None) -> bool:
    if not url:
        return False
    return "lknpd.nalog" in urllib.parse.urlparse(url).netloc.casefold()
