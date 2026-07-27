from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ozon_ord_sync.application.sheet_parser import parse_decimal

LEGAL_TYPE_ENTREPRENEUR = "LEGAL_TYPE_ENTREPRENEUR"
LEGAL_TYPE_INDIVIDUAL = "LEGAL_TYPE_INDIVIDUAL"
PERFORMER_STATUS_ENTREPRENEUR = "entrepreneur"
PERFORMER_STATUS_SELF_EMPLOYED = "self_employed"

_ADDRESS_LABEL = re.compile(
    r"^(Юр\.?\s*адрес|Юридический\s+адрес|Адрес)\s*:\s*(.*)$",
    re.IGNORECASE,
)
_ADDRESS_STOP = re.compile(
    r"^(e-?mail|эл\.?\s*почта|электронная\s+почта|инн\b|огрнип|огрн|кпп|"
    r"р\s*/\s*с|к\s*/\s*с|корр|бик|банк|реквизиты|генеральн|тел\b|телефон|"
    r"_{3,}|приложение|заказчик|исполнитель|передан\s+через|страница\s+\d)",
    re.IGNORECASE,
)


@dataclass
class ContractInfo:
    contract_number: str | None
    contract_date: date | None
    customer_name: str | None
    customer_inn: str | None
    performer_name: str | None
    performer_inn: str | None
    performer_legal_type: str
    performer_status: str | None
    performer_address: str | None
    total_amount: Decimal | None
    text: str


def parse_contract_text(text: str) -> ContractInfo:
    return ContractInfo(
        contract_number=_first_match(r"Договор[^№\n]*№\s*([^\s\n]+)", text),
        contract_date=_parse_contract_date(text),
        customer_name=_parse_customer_name(text),
        customer_inn=_parse_customer_inn(text),
        performer_name=_parse_performer_name(text),
        performer_inn=_parse_performer_inn(text),
        performer_legal_type=_parse_performer_legal_type(text),
        performer_status=_parse_performer_status(text),
        performer_address=_parse_performer_address(text),
        total_amount=_parse_contract_amount(text),
        text=text,
    )


def _parse_customer_inn(text: str) -> str | None:
    # Customer (ООО) INN is the 10-digit one paired with КПП in the requisites table.
    section = _requisites_section(text)
    return _first_match(r"ИНН[:\s]*(\d{10})\s*/?\s*КПП", section)


def _parse_performer_address(text: str) -> str | None:
    # Requisites are column-major: the whole Заказчик block, then the whole Исполнитель
    # block. The customer uses the full "Юридический адрес:" label; the performer uses
    # the abbreviated "Юр.адрес:". Collect labelled address blocks (each may span several
    # lines until the next field) and pick the performer's.
    lines = _requisites_section(text).splitlines()
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        match = _ADDRESS_LABEL.match(lines[index].strip())
        if not match:
            index += 1
            continue

        label = match.group(1).casefold()
        if "юридическ" in label:
            kind = "customer"
        elif label.replace(" ", "").startswith("юр"):
            kind = "performer"
        else:
            kind = "plain"

        parts = [match.group(2).strip()]
        index += 1
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped or _ADDRESS_STOP.match(stripped):
                break
            parts.append(stripped)
            index += 1

        address = _clean_address(" ".join(part for part in parts if part))
        if address:
            blocks.append((kind, address))

    return _select_performer_address(blocks)


def _select_performer_address(blocks: list[tuple[str, str]]) -> str | None:
    performer = [address for kind, address in blocks if kind == "performer"]
    if performer:
        return performer[0]
    # No abbreviated label: the customer block comes first in column-major order,
    # so a second address block is the performer's.
    if len(blocks) >= 2:
        return blocks[-1][1]
    return None


def _clean_address(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().rstrip(",").strip()


def _parse_performer_status(text: str) -> str | None:
    lowered = text.casefold()
    if "огрнип" in lowered or "индивидуальный предприниматель" in lowered:
        return PERFORMER_STATUS_ENTREPRENEUR
    if re.search(r"(?:в качестве\s+)?самозанят", lowered) or re.search(
        r"плательщик\w*\s+налога\s+на\s+профессиональный\s+доход",
        lowered,
    ):
        return PERFORMER_STATUS_SELF_EMPLOYED
    return None


def _parse_performer_legal_type(text: str) -> str:
    # The performer is an individual entrepreneur (ИП) when the contract mentions
    # "Индивидуальный предприниматель" or carries an ОГРНИП; otherwise treat them as a
    # physical person / self-employed (СЗ). The customer is always an ООО, so these
    # markers can only refer to the performer.
    lowered = text.casefold()
    if "огрнип" in lowered or "индивидуальный предприниматель" in lowered:
        return LEGAL_TYPE_ENTREPRENEUR
    return LEGAL_TYPE_INDIVIDUAL


def _parse_performer_inn(text: str) -> str | None:
    # The performer INN lives in the "Реквизиты и подписи Сторон" table. PDFKit may
    # flatten that two-column table row-by-row or column-by-column, so identify the
    # performer INN by exclusion instead of by position: the customer (ООО) INN is the
    # 10-digit one paired with КПП; the performer INN is any other labelled ИНН, and
    # when ambiguous we prefer the 12-digit one (ИП / самозанятый).
    section = _requisites_section(text)
    customer_inn = _first_match(r"ИНН[:\s]*(\d{10})\s*/?\s*КПП", section)
    labelled = re.findall(r"ИНН[:\s]*(\d{10,12})(?!\d)", section)
    non_customer = [inn for inn in labelled if inn != customer_inn]
    if not non_customer:
        return None
    twelve_digit = [inn for inn in non_customer if len(inn) == 12]
    return twelve_digit[0] if twelve_digit else non_customer[0]


def _requisites_section(text: str) -> str:
    match = re.search(r"Реквизиты\s+и\s+подписи", text, flags=re.IGNORECASE)
    return text[match.start() :] if match else text


def _parse_contract_date(text: str) -> date | None:
    months = {
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
    match = re.search(
        r"(?:\b|[«„“\"])(\d{1,2})[»”\"]?\s+([а-яё]+)\s+(\d{4})\s*г?\.?",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        day = int(match.group(1))
        month = months.get(match.group(2).casefold())
        if month is not None:
            return date(int(match.group(3)), month, day)

    numeric = re.search(r"(?:от\s*)?(\d{2})\.(\d{2})\.(\d{4})\b", text)
    if numeric:
        day, month, year = map(int, numeric.groups())
        return date(year, month, day)
    return None


def _parse_customer_name(text: str) -> str | None:
    match = re.search(r"ответственностью\s+[“\"]([^”\"]+)[”\"]", text)
    return match.group(1) if match else None


def _parse_performer_name(text: str) -> str | None:
    collapsed = re.sub(r"\s+", " ", text)

    # ИП: "Индивидуальный предприниматель <Фамилия Имя Отчество>". ORD stores the bare
    # ФИО (no "Индивидуальный предприниматель" prefix), so capture only the name.
    match = re.search(
        r"Индивидуальный\s+предприниматель\s+"
        r"([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2})",
        collapsed,
    )
    if match:
        return match.group(1).strip()

    # Other templates: "... «Заказчик», и <name>, зарегистрирован|являющ".
    match = re.search(
        r"именуемое в дальнейшем «Заказчик»,\s*и\s*(.+?),\s*(?:зарегистрирован|являющ)",
        collapsed,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _parse_contract_amount(text: str) -> Decimal | None:
    match = re.search(r"ИТОГО:\s*([\d\s\xa0]+)(?:руб|₽)", text, flags=re.IGNORECASE)
    if not match:
        match = re.search(
            r"Стоимость услуг составляет\s*([\d\s\xa0]+)(?:руб|₽)",
            text,
            flags=re.IGNORECASE,
        )
    return parse_decimal(match.group(1)) if match else None


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None
