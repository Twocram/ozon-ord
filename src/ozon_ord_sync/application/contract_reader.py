from __future__ import annotations

import re
import tempfile
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from ozon_ord_sync.application.contract_parser import ContractInfo, parse_contract_text
from ozon_ord_sync.application.creative_builder import (
    build_creative_payload,
    upload_creative_media,
)
from ozon_ord_sync.application.name_matching import names_match
from ozon_ord_sync.application.sheet_parser import parse_creative_sheet
from ozon_ord_sync.infrastructure.apps_script import AppsScriptClient
from ozon_ord_sync.infrastructure.document_text import extract_document_text
from ozon_ord_sync.infrastructure.drive_files import download_drive_file
from ozon_ord_sync.infrastructure.google_sheets import (
    fetch_sheet_rows,
    google_sheet_id,
)
from ozon_ord_sync.infrastructure.ozon_ord import AdminOzonOrdClient

ORGANISATION_SUMMARY_FIELDS = ("id", "inn", "name", "legalType", "kpp", "address")
CONTRACT_SUMMARY_FIELDS = (
    "id",
    "contractNumber",
    "contractDate",
    "contractType",
    "subjectType",
    "organisationCustomerId",
    "organisationPerformerId",
    "price",
)


@dataclass
class CreativeContractRow:
    row_number: int
    channel_url: str | None
    creative_name: str | None
    contract_url: str | None
    performer_name: str | None
    performer_inn: str | None
    counterparty: dict[str, Any] | None = None
    ord_contract: dict[str, Any] | None = None
    creative: dict[str, Any] | None = None
    content_type: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_contracts_from_creative_sheet(
    sheet_url: str,
    admin_client: AdminOzonOrdClient | None = None,
    apps_script_client: AppsScriptClient | None = None,
    create_missing: bool = False,
) -> list[CreativeContractRow]:
    _, rows = parse_creative_sheet(sheet_url)
    results: list[CreativeContractRow] = []
    with tempfile.TemporaryDirectory() as tmp:
        target_dir = Path(tmp)
        for row in rows:
            contract_url = row.raw.get("ssylka_na_dogovor")
            channel_url = row.raw.get("channel_url")
            creative_name = row.raw.get("nazvanie_kreativa")

            if not contract_url:
                results.append(
                    CreativeContractRow(
                        row_number=row.row_number,
                        channel_url=channel_url,
                        creative_name=creative_name,
                        contract_url=None,
                        performer_name=None,
                        performer_inn=None,
                        error="missing Ссылка на договор",
                    )
                )
                continue

            try:
                downloaded = download_drive_file(contract_url, target_dir)
                text = extract_document_text(downloaded.path, downloaded.content_type)
                contract = parse_contract_text(text)
            except Exception as error:
                results.append(
                    CreativeContractRow(
                        row_number=row.row_number,
                        channel_url=channel_url,
                        creative_name=creative_name,
                        contract_url=contract_url,
                        performer_name=None,
                        performer_inn=None,
                        error=str(error),
                    )
                )
                continue

            counterparty: dict[str, Any] | None = None
            ord_contract: dict[str, Any] | None = None
            creative: dict[str, Any] | None = None
            if admin_client is not None:
                counterparty = _check_counterparty(
                    admin_client, contract, create_missing=create_missing
                )
                performer_id = _counterparty_organisation_id(counterparty)
                ord_contract = _check_contract(
                    admin_client,
                    contract,
                    performer_id,
                    create_missing=create_missing,
                )
                creative = _build_creative(
                    admin_client,
                    row.raw,
                    _contract_id(ord_contract),
                    target_dir,
                    create_missing=create_missing,
                )

            results.append(
                CreativeContractRow(
                    row_number=row.row_number,
                    channel_url=channel_url,
                    creative_name=creative_name,
                    contract_url=contract_url,
                    performer_name=contract.performer_name,
                    performer_inn=contract.performer_inn,
                    counterparty=counterparty,
                    ord_contract=ord_contract,
                    creative=creative,
                    content_type=downloaded.content_type,
                )
            )

    if apps_script_client is not None:
        _write_creative_erids(apps_script_client, sheet_url, results)
    return results


def _write_creative_erids(
    apps_script_client: AppsScriptClient,
    sheet_url: str,
    results: list[CreativeContractRow],
) -> None:
    erid_rows = [
        {"row_number": row.row_number, "erid": row.creative["marker"]}
        for row in results
        if row.creative and row.creative.get("marker")
    ]
    if not erid_rows:
        return

    response = apps_script_client.update_creative_erids(
        erid_rows,
        spreadsheet_id=google_sheet_id(sheet_url),
        erid_column=_resolve_erid_column(sheet_url),
    )
    written = bool(response.get("ok", True))
    for row in results:
        if row.creative and row.creative.get("marker"):
            row.creative["erid_written"] = written
            if not written:
                row.creative["erid_error"] = response.get("error")


def _resolve_erid_column(sheet_url: str) -> str:
    # The sheet header may be "Erid", "erid ", etc. Resolve the exact header text so the
    # Apps Script's exact-name lookup matches regardless of case/spacing.
    try:
        header, _ = fetch_sheet_rows(sheet_url)
    except Exception:
        return "erid"
    for cell in header:
        if isinstance(cell, str) and cell.strip().casefold() == "erid":
            return cell
    return "erid"


def _build_creative(
    admin_client: AdminOzonOrdClient,
    raw_row: dict[str, Any],
    contract_id: str | None,
    target_dir: Path,
    create_missing: bool = False,
) -> dict[str, Any]:
    photo_url = raw_row.get("ssylka_na_foto_posta")
    if not contract_id:
        return {"created": None, "error": "contract is unknown"}
    if not photo_url:
        return {"created": None, "error": "missing Ссылка на фото поста"}

    if not create_missing:
        # Dry-run: skip the media upload (a write) and creation entirely.
        return {"created": False, "would_create": True}

    try:
        media = upload_creative_media(admin_client, photo_url, target_dir)
    except Exception as error:
        return {"created": False, "error": f"media upload failed: {error}"}

    payload = build_creative_payload(raw_row, contract_id, media)
    try:
        response = admin_client.create_creative(payload)
    except Exception as error:
        return {"created": False, "error": str(error), "media_id": media.get("id")}

    return {
        "created": True,
        "marker": _extract_created_marker(response),
        "media_id": media.get("id"),
        "create_response": response,
    }


def _contract_id(ord_contract: dict[str, Any] | None) -> str | None:
    if not ord_contract:
        return None
    contract = ord_contract.get("contract")
    if isinstance(contract, dict) and contract.get("id"):
        return str(contract["id"])
    return None


def _extract_created_marker(response: dict[str, Any]) -> str | None:
    for node in (response, response.get("creative") if isinstance(response, dict) else None):
        if isinstance(node, dict):
            marker = node.get("marker")
            if isinstance(marker, str) and marker:
                return marker
    return None


def _counterparty_organisation_id(counterparty: dict[str, Any] | None) -> str | None:
    if not counterparty:
        return None
    organisation = counterparty.get("organisation")
    if isinstance(organisation, dict):
        organisation_id = organisation.get("id")
        return str(organisation_id) if organisation_id else None
    return None


def _check_counterparty(
    admin_client: AdminOzonOrdClient,
    contract: ContractInfo,
    create_missing: bool = False,
) -> dict[str, Any]:
    inn = contract.performer_inn
    name = contract.performer_name

    if inn:
        lookup_by, query_value = "inn", inn
    elif name:
        lookup_by, query_value = "name", name
    else:
        return {
            "found": None,
            "lookup_by": None,
            "matches": 0,
            "organisation": None,
            "error": "no ИНН or ФИО to search counterparty",
        }

    try:
        matches = _search_organisations(admin_client, query_value, inn, name, lookup_by)
    except Exception as error:
        return {
            "found": None,
            "lookup_by": lookup_by,
            "matches": 0,
            "organisation": None,
            "error": str(error),
        }

    result = _match_result(lookup_by, matches)
    if matches:
        return result

    # Counterparty missing: prepare the "Добавление контрагента" payload.
    payload = build_organisation_payload(contract)
    result["create_payload"] = payload

    if not create_missing:
        # Dry-run: return the prepared payload without sending a create request.
        result["created"] = False
        return result

    try:
        result["create_response"] = admin_client.create_organisation(payload)
    except Exception as error:
        result["created"] = False
        result["create_error"] = str(error)
        return result

    result["created"] = True
    # Re-search so the caller gets the freshly created organisation.
    try:
        rematches = _search_organisations(
            admin_client, query_value, inn, name, lookup_by
        )
    except Exception as error:
        result["research_error"] = str(error)
        return result

    result.update(_match_result(lookup_by, rematches))
    result["create_payload"] = payload
    result["created"] = True
    return result


def _match_result(lookup_by: str, matches: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "found": bool(matches),
        "lookup_by": lookup_by,
        "matches": len(matches),
        "organisation": _organisation_summary(matches[0]) if len(matches) == 1 else None,
    }


def _check_contract(
    admin_client: AdminOzonOrdClient,
    contract: ContractInfo,
    performer_id: str | None,
    create_missing: bool = False,
) -> dict[str, Any]:
    if not contract.contract_number:
        return {"found": None, "error": "no contract number in PDF"}
    if not performer_id:
        return {"found": None, "error": "performer organisation is unknown"}

    customer_id, customer_error = _resolve_customer_id(admin_client, contract.customer_inn)
    if customer_error:
        return {"found": None, "error": customer_error}

    try:
        existing = _find_contract(
            admin_client, contract.contract_number, contract.contract_date
        )
    except Exception as error:
        return {"found": None, "error": str(error)}

    if existing is not None:
        return {"found": True, "contract": _contract_summary(existing)}

    payload = build_contract_payload(contract, customer_id, performer_id)
    result: dict[str, Any] = {"found": False, "create_payload": payload}

    if not create_missing:
        result["created"] = False
        return result

    try:
        result["create_response"] = admin_client.create_contract(payload)
        result["created"] = True
    except Exception as error:
        result["created"] = False
        result["create_error"] = str(error)
        return result

    # Re-search to expose the freshly created contract (with its id) to the caller.
    try:
        created = _find_contract(
            admin_client, contract.contract_number, contract.contract_date
        )
        if created is not None:
            result["contract"] = _contract_summary(created)
            result["found"] = True
    except Exception as error:
        result["research_error"] = str(error)
    return result


def _resolve_customer_id(
    admin_client: AdminOzonOrdClient,
    customer_inn: str | None,
) -> tuple[str | None, str | None]:
    if not customer_inn:
        return None, "no customer ИНН in contract"

    response = admin_client.list_organisations(
        {"pageSize": 20, "orderBy": "DESC", "opf": customer_inn}
    )
    matches = [
        org
        for org in (response.get("organisation") or [])
        if str(org.get("inn") or "") == customer_inn
    ]
    if len(matches) == 1:
        return str(matches[0].get("id")), None
    if not matches:
        return None, f"customer organisation not found for ИНН {customer_inn}"
    return None, f"multiple customer organisations for ИНН {customer_inn}"


def _find_contract(
    admin_client: AdminOzonOrdClient,
    number: str,
    contract_date: Any,
) -> dict[str, Any] | None:
    response = admin_client.list_contracts(
        {"pageSize": 10, "orderBy": "ASC", "contractNumber": number}
    )
    date_iso = contract_date.isoformat() if contract_date else None
    for item in response.get("contract", []):
        if item.get("contractNumber") == number and (
            date_iso is None or item.get("contractDate") == date_iso
        ):
            return item
    return None


def build_contract_payload(
    contract: ContractInfo,
    customer_id: str | None,
    performer_id: str | None,
) -> dict[str, Any]:
    # Mirrors the browser "Добавление договора" POST body.
    return {
        "comment": "",
        "additionalContractNumber": "",
        "contractDate": contract.contract_date.isoformat()
        if contract.contract_date
        else "",
        "expirationDate": "",
        "contractNumber": contract.contract_number or "",
        "contractType": "CONTRACT_TYPE_SERVICE",
        "isCreativeReporter": False,
        "organisationCustomerId": customer_id or "",
        "organisationPerformerId": performer_id or "",
        "price": _format_price(contract.total_amount),
        "subjectType": "SUBJECT_TYPE_DISTRIBUTION",
    }


def _format_price(amount: Decimal | None) -> str:
    if amount is None:
        return ""
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _contract_summary(contract: dict[str, Any]) -> dict[str, Any]:
    return {field: contract.get(field) for field in CONTRACT_SUMMARY_FIELDS}


def _search_organisations(
    admin_client: AdminOzonOrdClient,
    query_value: str,
    inn: str | None,
    name: str | None,
    lookup_by: str,
) -> list[dict[str, Any]]:
    response = admin_client.list_organisations(
        {"pageSize": 20, "orderBy": "DESC", "opf": query_value}
    )
    organisations = response.get("organisation") or []
    return [
        org
        for org in organisations
        if _organisation_matches(org, inn=inn, name=name, lookup_by=lookup_by)
    ]


def build_organisation_payload(contract: ContractInfo) -> dict[str, Any]:
    # Mirrors the browser "Добавление контрагента" POST body. isPp=true marks a
    # рекламораспространитель (channel owner), which is what our contractors are.
    # ИП -> LEGAL_TYPE_ENTREPRENEUR, СЗ/Физ.лицо -> LEGAL_TYPE_INDIVIDUAL.
    return {
        "address": contract.performer_address or "",
        "isOpc": False,
        "isPp": True,
        "legalType": contract.performer_legal_type,
        "platforms": [],
        "name": contract.performer_name or "",
        "inn": contract.performer_inn or "",
    }


def _organisation_matches(
    org: dict[str, Any],
    inn: str | None,
    name: str | None,
    lookup_by: str,
) -> bool:
    if lookup_by == "inn":
        return str(org.get("inn") or "") == inn
    return _name_matches(org.get("name"), name)


def _organisation_summary(org: dict[str, Any]) -> dict[str, Any]:
    return {field: org.get(field) for field in ORGANISATION_SUMMARY_FIELDS}


def _name_matches(candidate: str | None, target: str | None) -> bool:
    return names_match(candidate, target) is True
