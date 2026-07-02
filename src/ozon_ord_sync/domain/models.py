from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass
class ParsedRow:
    row_number: int
    manager: str | None
    month: date | None
    platform: str | None
    creative_id: str | None
    channel_url: str | None
    executor: str | None
    contractor: str | None
    price_with_tax: Decimal | None
    publication_date: date | None
    display_date: date | None
    reach: int | None
    mark: str | None
    error: str | None
    raw: dict[str, Any]


@dataclass
class ParsedPlatformRow:
    row_number: int
    name: str | None
    url: str | None
    raw: dict[str, Any]


@dataclass
class RowIssue:
    row_number: int
    messages: list[str]


@dataclass
class OzonOrdPayload:
    row_number: int
    creative: str
    platform: str
    campaign_type: str
    factual_impressions: int
    planned_impressions: int
    factual_display_start_date: date
    factual_display_end_date: date
    planned_display_start_date: date
    planned_display_end_date: date
    vat_rate: str
    service_amount: Decimal
    amount_mode: str
    unit_price_with_vat: Decimal


@dataclass
class OzonOrdPlatformPayload:
    externalPlatformId: str
    appName: str
    platformType: str
    url: str
    comment: str


@dataclass
class OzonOrdStatisticPayload:
    externalStatisticId: str
    externalCreativeId: str
    externalPlatformId: str
    dateStartFact: date
    dateEndFact: date
    dateStartPlan: date
    dateEndPlan: date
    viewsCountByFact: str
    viewsCountByInvoice: str
    moneySpent: str
    unitCost: str
    withNds: bool
    comment: str


@dataclass
class OzonOrdAdminStatisticPayload:
    creativeId: str
    platformId: str
    price: dict[str, str | bool]
    comment: str
    dateEndFact: date
    dateEndPlan: date
    paymentType: str
    dateStartFact: date
    dateStartPlan: date
    unitCost: str
    viewsCountByFact: str
    viewsCountByInvoice: str
    sameDate: bool
    sameViews: bool
    isAutoCalc: bool
    isSelfPromo: bool
    isNative: bool
    externalId: str
    fromDate: str
    toDate: str


@dataclass
class SyncBatch:
    platforms: list[OzonOrdPlatformPayload]
    statistics: list[OzonOrdStatisticPayload]
    mapping_errors: list[str]


@dataclass
class PlatformSyncBatch:
    platforms: list[OzonOrdPlatformPayload]
    mapping_errors: list[str]


@dataclass
class ResolvedStatisticPayload:
    row_number: int
    payload: OzonOrdAdminStatisticPayload
