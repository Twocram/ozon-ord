from __future__ import annotations

import calendar
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from ozon_ord_sync.application.contract_parser import ContractInfo, parse_contract_text
from ozon_ord_sync.application.name_matching import name_contains, names_match
from ozon_ord_sync.application.receipt_parser import (
    CONFIDENCE_HIGH,
    ReceiptInfo,
    document_type_matches,
    parse_receipt_text,
    self_employed_receipt_number_is_valid,
    verify_receipt_number,
)
from ozon_ord_sync.application.sheet_parser import parse_document_check_sheet
from ozon_ord_sync.application.vat_checker import vat_check_note
from ozon_ord_sync.domain.models import ParsedDocumentCheckRow
from ozon_ord_sync.infrastructure.document_text import extract_document_text
from ozon_ord_sync.infrastructure.drive_files import download_drive_file
from ozon_ord_sync.infrastructure.ozon_ord import AdminOzonOrdClient

# Rows that never go to ORD. "Как подписано" is matched on "Консоль" only: "ЭДО"
# is a normal signing method there and those rows do carry an act. In "Чеки/Акты"
# any mention of ЭДО or the console is a note instead of a document link
# ("в ЭДО подписан", "в консоли"), so the row has nothing to register.
# Both patterns are case-insensitive and stemmed ("Консоль", "в консоли").
_SIGNATURE_SKIP_RE = re.compile(r"консол", re.IGNORECASE)
_RECEIPTS_SKIP_RE = re.compile(r"консол|\bэдо\b", re.IGNORECASE)


@dataclass
class InvoicePayloadDraft:
    row_number: int
    ok: bool
    issues: list[str]
    checks: dict[str, bool | None]
    sheet: dict[str, Any]
    receipt: ReceiptInfo | None
    contract: ContractInfo | None
    payload: dict[str, Any] | None
    skip_reason: str | None = None
    vat_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_invoice_payload_drafts(
    sheet_url: str,
    admin_client: AdminOzonOrdClient | None = None,
) -> list[InvoicePayloadDraft]:
    _, rows = parse_document_check_sheet(sheet_url)
    drafts: list[InvoicePayloadDraft] = []
    with tempfile.TemporaryDirectory() as tmp:
        target_dir = Path(tmp)
        for row in rows:
            drafts.append(_build_row_draft(row, target_dir, admin_client))
    return drafts


def row_skip_reason(row: ParsedDocumentCheckRow) -> str | None:
    """Why a row must not be registered in ORD, or None when it should be.

    Rows signed in the console, and rows whose «Чеки/Акты» cell holds a note
    ("в ЭДО подписан") instead of a document, are handled outside this pipeline:
    skip them instead of validating and reporting them as broken.
    """
    for label, value, pattern in (
        ("Как подписано", row.signature_type, _SIGNATURE_SKIP_RE),
        ("Чеки/Акты", row.receipts_acts_url, _RECEIPTS_SKIP_RE),
    ):
        if value and pattern.search(value):
            return f"«{label}»: {value.strip()}"
    return None


def _build_row_draft(
    row: ParsedDocumentCheckRow,
    target_dir: Path,
    admin_client: AdminOzonOrdClient | None,
) -> InvoicePayloadDraft:
    issues: list[str] = []
    receipt: ReceiptInfo | None = None
    contract: ContractInfo | None = None

    skip_reason = row_skip_reason(row)
    if skip_reason:
        return InvoicePayloadDraft(
            row_number=row.row_number,
            ok=False,
            issues=[],
            checks={},
            sheet=_sheet_summary(row),
            receipt=None,
            contract=None,
            payload=None,
            skip_reason=skip_reason,
        )

    try:
        if row.receipts_acts_url is None:
            issues.append("missing Чеки/Акты link")
        else:
            receipt_file = download_drive_file(row.receipts_acts_url, target_dir)
            receipt_text = extract_document_text(
                receipt_file.path,
                receipt_file.content_type,
            )
            receipt = verify_receipt_number(
                parse_receipt_text(receipt_text, row.receipts_acts_url)
            )
            if receipt.receipt_number_verified is False:
                issues.append(
                    f"ЛК НПД не подтвердил номер чека: {receipt.receipt_number}"
                )
    except Exception as error:
        issues.append(f"receipt read failed: {error}")

    try:
        if row.contract_url is None:
            issues.append("missing Договор link")
        else:
            contract_file = download_drive_file(row.contract_url, target_dir)
            contract_text = extract_document_text(
                contract_file.path,
                contract_file.content_type,
            )
            contract = parse_contract_text(contract_text)
    except Exception as error:
        issues.append(f"contract read failed: {error}")

    payload = _payload_from_parts(row, receipt, contract, issues)
    checks = _checks(row, receipt, contract)
    issues.extend(_check_issues(checks))
    if payload is not None and contract is not None and admin_client is not None:
        _resolve_ord_entities(payload, contract, admin_client, issues)
    issues.extend(_missing_payload_issues(payload, receipt))

    return InvoicePayloadDraft(
        row_number=row.row_number,
        ok=not issues,
        issues=issues,
        checks=checks,
        sheet=_sheet_summary(row),
        receipt=receipt,
        contract=contract,
        payload=payload,
        # VAT never blocks the row: it only asks for a note in «Проверка».
        vat_note=vat_check_note(
            contract.text if contract else "",
            receipt.text if receipt else "",
            contract.performer_status if contract else None,
        ),
    )


def _sheet_summary(row: ParsedDocumentCheckRow) -> dict[str, Any]:
    return {
        "payment_amount": row.payment_amount,
        "counterparty": row.counterparty,
        "signature_type": row.signature_type,
        "expense_month": row.expense_month,
        "contract_url": row.contract_url,
        "receipts_acts_url": row.receipts_acts_url,
    }


def _payload_from_parts(
    row: ParsedDocumentCheckRow,
    receipt: ReceiptInfo | None,
    contract: ContractInfo | None,
    issues: list[str],
) -> dict[str, Any] | None:
    amount = (receipt.total_amount if receipt else None) or row.payment_amount
    invoice_date = receipt.issued_at.date() if receipt and receipt.issued_at else None
    period = _period(row, invoice_date)

    if amount is None:
        issues.append("missing amount")
        return None

    price = _price(amount)
    return {
        "contractId": None,
        "comment": "",
        "isSocial": False,
        "isSocialQuota": False,
        "customerAddress": "",
        "customerLegalType": "LEGAL_TYPE_LEGAL",
        "performerAddress": "",
        "performerLegalType": "LEGAL_TYPE_INDIVIDUAL",
        "servicePrice": price,
        "contractPrice": f"{amount:.2f}",
        "rrOrderContractIds": [],
        "clientRole": "ORGANISATION_ROLE_RD",
        "contractorRole": "ORGANISATION_ROLE_RR",
        "endDate": period[1].isoformat() if period else None,
        "agentActingForPublisher": False,
        "performerId": None,
        "customerId": None,
        "rrOrderContractLabels": [],
        "startDate": period[0].isoformat() if period else None,
        "invoiceDate": invoice_date.isoformat() if invoice_date else None,
        # A numberless act form is registered with an empty act number.
        "invoiceNumber": (receipt.receipt_number or "") if receipt else None,
        "isSelfPromo": False,
        "invoiceType": "INVOICE_TYPE_INVOICE",
        "contractDate": contract.contract_date.isoformat()
        if contract and contract.contract_date
        else None,
        "contractNumber": contract.contract_number if contract else None,
        "contractType": "CONTRACT_TYPE_SERVICE",
        "customerName": contract.customer_name if contract else None,
        "performerName": contract.performer_name
        if contract and contract.performer_name
        else receipt.seller_name if receipt else None,
        "selectedInitialContract": None,
        "priceSumCalculated": float(amount),
        "priceSumWoNdsCalculated": float(amount),
        "contracts": [
            {
                "creatives": [],
                "contractId": None,
                "isSocial": False,
                "isSocialQuota": False,
                "price": {
                    "amount": _amount(amount),
                    "excludingAmount": _amount(amount),
                    "vatRate": "",
                    "withNdsSelected": False,
                },
            }
        ],
    }


def _resolve_ord_entities(
    payload: dict[str, Any],
    contract: ContractInfo,
    admin_client: AdminOzonOrdClient,
    issues: list[str],
) -> None:
    if not contract.contract_number:
        return

    response = admin_client.list_contracts(
        {
            "pageSize": 100,
            "orderBy": "ASC",
            "contractNumber": contract.contract_number,
        }
    )
    matches = [
        item
        for item in response.get("contract", [])
        if _same_contract_number(item.get("contractNumber"), contract.contract_number)
        and (
            contract.contract_date is None
            or item.get("contractDate") == contract.contract_date.isoformat()
        )
    ]
    if len(matches) != 1:
        issues.append(
            f"ORD contract matches: {len(matches)} for {contract.contract_number}"
        )
        return

    ord_contract = matches[0]
    contract_id = ord_contract.get("id")
    payload["contractId"] = contract_id
    payload["selectedInitialContract"] = ord_contract
    payload["customerId"] = ord_contract.get("organisationCustomerId") or (
        ord_contract.get("customer") or {}
    ).get("id")
    payload["performerId"] = ord_contract.get("organisationPerformerId") or (
        ord_contract.get("performer") or {}
    ).get("id")
    payload["customerName"] = (ord_contract.get("customer") or {}).get("title")
    payload["performerName"] = (ord_contract.get("performer") or {}).get("title")
    payload["customerAddress"] = (ord_contract.get("customer") or {}).get("address") or ""
    payload["performerAddress"] = (ord_contract.get("performer") or {}).get("address") or ""
    payload["customerLegalType"] = (ord_contract.get("customer") or {}).get(
        "organizationType"
    ) or payload["customerLegalType"]
    payload["performerLegalType"] = (ord_contract.get("performer") or {}).get(
        "organizationType"
    ) or payload["performerLegalType"]
    payload["contracts"][0]["contractId"] = contract_id

    if contract_id:
        creative_response = admin_client.list_admin_creatives(
            {
                "pageSize": 100,
                "orderBy": "DESC",
                "contractId": contract_id,
            }
        )
        payload["contracts"][0]["creatives"] = [
            {"creativeId": creative.get("id")}
            for creative in creative_response.get("creative", [])
            if creative.get("id")
        ]


def _price(amount: Decimal) -> dict[str, Any]:
    return {
        "amount": _amount(amount),
        "vatRate": "",
        "intermediaryReports": [],
        "vatAmount": "0",
        "excludingAmount": _amount(amount),
        "autoCalc": True,
        "withNdsSelected": False,
        "manualCalc": False,
    }


def _amount(amount: Decimal) -> str:
    return format(amount.normalize(), "f")


def _period(
    row: ParsedDocumentCheckRow,
    fallback_date: date | None,
) -> tuple[date, date] | None:
    months = {
        "январь": 1,
        "февраль": 2,
        "март": 3,
        "апрель": 4,
        "май": 5,
        "июнь": 6,
        "июль": 7,
        "август": 8,
        "сентябрь": 9,
        "октябрь": 10,
        "ноябрь": 11,
        "декабрь": 12,
    }
    year = row.submitted_at.year if row.submitted_at else fallback_date.year if fallback_date else None
    month = months.get((row.expense_month or "").strip().casefold())
    if year is None:
        return None
    if month is None:
        month = fallback_date.month if fallback_date else None
    if month is None:
        return None
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _checks(
    row: ParsedDocumentCheckRow,
    receipt: ReceiptInfo | None,
    contract: ContractInfo | None,
) -> dict[str, bool | None]:
    return {
        "sheet_receipt_amount": None
        if row.payment_amount is None or receipt is None or receipt.total_amount is None
        else row.payment_amount == receipt.total_amount,
        "sheet_contract_amount": None
        if row.payment_amount is None or contract is None or contract.total_amount is None
        else row.payment_amount == contract.total_amount,
        "receipt_contract_amount": None
        if receipt is None
        or receipt.total_amount is None
        or contract is None
        or contract.total_amount is None
        else receipt.total_amount == contract.total_amount,
        "receipt_contract_name": None
        if receipt is None or contract is None
        else _receipt_name_check(
            names_match(receipt.seller_name, contract.performer_name),
            receipt,
        ),
        "sheet_receipt_name": None
        if receipt is None
        else _receipt_name_check(
            name_contains(row.counterparty, receipt.seller_name),
            receipt,
        ),
        "sheet_contract_name": None
        if contract is None
        else name_contains(row.counterparty, contract.performer_name),
        "contract_receipt_document_type": None
        if contract is None or receipt is None
        else document_type_matches(
            contract.performer_status,
            receipt.document_type,
        ),
        "self_employed_receipt_number": None
        if contract is None or receipt is None
        else self_employed_receipt_number_is_valid(
            contract.performer_status,
            receipt.document_type,
            receipt.receipt_number,
        ),
    }


def _check_issues(checks: dict[str, bool | None]) -> list[str]:
    return [f"check failed: {key}" for key, value in checks.items() if value is False]


def _missing_payload_issues(
    payload: dict[str, Any] | None,
    receipt: ReceiptInfo | None = None,
) -> list[str]:
    if payload is None:
        return []
    required = [
        "contractId",
        "performerId",
        "customerId",
        "invoiceDate",
        "invoiceNumber",
        "contractDate",
        "contractNumber",
        "customerName",
        "performerName",
    ]
    if receipt is not None and receipt.number_optional:
        # "Акт сдачи-приемки оказанных услуг" has no number to read — register it
        # with an empty act number rather than holding the row back.
        required.remove("invoiceNumber")
    issues = [f"payload missing: {key}" for key in required if not payload.get(key)]
    if not payload["contracts"][0].get("creatives"):
        issues.append("payload missing: contracts[0].creatives")
    if payload.get("performerLegalType") in {
        "LEGAL_TYPE_INDIVIDUAL",
        "LEGAL_TYPE_ENTREPRENEUR",
    } and not payload.get("performerAddress"):
        issues.append("payload missing: performerAddress")
    return issues


def _same_contract_number(left: str | None, right: str | None) -> bool:
    # Contract numbers are compared case- and spacing-insensitively: "ЛР-2026/4"
    # in ORD and "лр-2026/ 4" from the PDF are the same contract.
    key = _contract_number_key(left)
    return bool(key) and key == _contract_number_key(right)


def _contract_number_key(value: str | None) -> str:
    return re.sub(r"[\s№]+", "", value or "").casefold()


def _receipt_name_check(result: bool | None, receipt: ReceiptInfo) -> bool | None:
    # A ФИО pulled out of a receipt by shape alone (no label, no patronymic) is a
    # guess: report a mismatch as "unknown" instead of failing the row.
    if result is False and receipt.seller_name_confidence != CONFIDENCE_HIGH:
        return None
    return result
