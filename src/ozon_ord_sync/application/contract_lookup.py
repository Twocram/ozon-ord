"""Finding a contract that is already registered in ORD.

Two things make the naive lookup miss contracts that the ORD interface finds:

* the search matches by substring, so "04062026" answers with every contract of
  that day — thirty-five of them — and a small page size hides the one we want;
* the number printed in the PDF is not always the number in ORD: a contract
  registered as "04062026" is printed as "№ 4062026".

So ask for a large page, then match the number segment by segment ignoring
leading zeros, together with the contract date, and fall back to the performer's
ФИО when several contracts share a number and a date.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ozon_ord_sync.application.name_matching import names_match
from ozon_ord_sync.infrastructure.ozon_ord import AdminOzonOrdClient

CONTRACT_SEARCH_PAGE_SIZE = 200


def find_ord_contracts(
    admin_client: AdminOzonOrdClient,
    number: str | None,
    contract_date: date | None,
    performer_name: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Contracts ORD holds under this number and date, plus a warning if truncated."""
    if not number:
        return [], None

    response = admin_client.list_contracts(
        {
            "pageSize": CONTRACT_SEARCH_PAGE_SIZE,
            "orderBy": "ASC",
            "contractNumber": number,
        }
    )
    items = response.get("contract") or []
    warning = (
        f"ORD contract search truncated at {CONTRACT_SEARCH_PAGE_SIZE} results"
        if len(items) >= CONTRACT_SEARCH_PAGE_SIZE
        else None
    )

    date_iso = contract_date.isoformat() if contract_date else None
    matches = [
        item
        for item in items
        if contract_numbers_match(item.get("contractNumber"), number)
        and (date_iso is None or item.get("contractDate") == date_iso)
    ]
    if len(matches) > 1 and performer_name:
        by_performer = [
            item
            for item in matches
            if names_match((item.get("performer") or {}).get("title"), performer_name)
        ]
        if by_performer:
            matches = by_performer
    return matches, warning


def contract_numbers_match(left: str | None, right: str | None) -> bool:
    left_key = contract_number_key(left)
    return bool(left_key) and left_key == contract_number_key(right)


def contract_number_key(value: str | None) -> tuple[str, ...]:
    """"№ 04062026/1" -> ("4062026", "1"): separators and leading zeros are typing."""
    parts = re.findall(r"[0-9a-zа-яё]+", (value or "").casefold())
    return tuple(part.lstrip("0") or "0" for part in parts)
