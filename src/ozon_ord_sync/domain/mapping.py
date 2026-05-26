from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

from ozon_ord_sync.domain.models import (
    OzonOrdAdminStatisticPayload,
    OzonOrdPayload,
    OzonOrdPlatformPayload,
    OzonOrdStatisticPayload,
    ParsedPlatformRow,
    ParsedRow,
)

DEFAULT_CAMPAIGN_TYPE = "Иное"
DEFAULT_VAT_RATE_LABEL = "Без НДС"
DEFAULT_PLATFORM_TYPE = "PLATFORM_TYPE_SITE"


def map_row_to_ozon_ord_payload(row: ParsedRow) -> OzonOrdPayload:
    creative_id = row.creative_id
    channel_url = row.channel_url
    reach = row.reach
    publication_date = row.publication_date
    price_with_tax = row.price_with_tax

    missing: list[str] = []
    if creative_id is None:
        missing.append("creative_id")
    if channel_url is None:
        missing.append("channel_url")
    if reach is None:
        missing.append("reach")
    if publication_date is None:
        missing.append("publication_date")
    if price_with_tax is None:
        missing.append("price_with_tax")

    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            f"Row {row.row_number}: missing required mapping fields: {joined}"
        )

    if (
        creative_id is None
        or channel_url is None
        or reach is None
        or publication_date is None
        or price_with_tax is None
    ):
        raise ValueError(f"Row {row.row_number}: missing required mapping fields")

    display_start_date = publication_date
    display_end_date = publication_date + timedelta(days=1)

    return OzonOrdPayload(
        row_number=row.row_number,
        creative=creative_id,
        platform=channel_url,
        campaign_type=DEFAULT_CAMPAIGN_TYPE,
        factual_impressions=reach,
        planned_impressions=reach,
        factual_display_start_date=display_start_date,
        factual_display_end_date=display_end_date,
        planned_display_start_date=display_start_date,
        planned_display_end_date=display_end_date,
        vat_rate=DEFAULT_VAT_RATE_LABEL,
        service_amount=price_with_tax,
        amount_mode="without_vat",
        unit_price_with_vat=price_with_tax,
    )


def build_platform_payload(row: ParsedRow) -> OzonOrdPlatformPayload:
    channel_url = row.channel_url
    if channel_url is None:
        raise ValueError(
            f"Row {row.row_number}: missing channel_url for platform payload"
        )

    return OzonOrdPlatformPayload(
        externalPlatformId=build_external_platform_id(channel_url),
        appName=build_platform_name(channel_url),
        platformType=DEFAULT_PLATFORM_TYPE,
        url=channel_url,
        comment=f"Imported from Google Sheets row {row.row_number}",
    )


def build_platform_sheet_payload(row: ParsedPlatformRow) -> OzonOrdPlatformPayload:
    name = row.name
    url = row.url

    missing: list[str] = []
    if name is None:
        missing.append("platform_name")
    if url is None:
        missing.append("platform_url")

    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            f"Row {row.row_number}: missing required platform fields: {joined}"
        )

    if name is None or url is None:
        raise ValueError(f"Row {row.row_number}: missing required platform fields")

    return OzonOrdPlatformPayload(
        externalPlatformId=build_external_platform_id(url),
        appName=name,
        platformType=DEFAULT_PLATFORM_TYPE,
        url=url,
        comment=f"Imported from Google Sheets platform row {row.row_number}",
    )


def build_statistic_payload(row: ParsedRow) -> OzonOrdStatisticPayload:
    payload = map_row_to_ozon_ord_payload(row)
    platform_payload = build_platform_payload(row)

    return OzonOrdStatisticPayload(
        externalStatisticId=build_external_statistic_id(
            creative_id=payload.creative,
            external_platform_id=platform_payload.externalPlatformId,
            display_start_date=payload.factual_display_start_date,
            display_end_date=payload.factual_display_end_date,
        ),
        externalCreativeId=payload.creative,
        externalPlatformId=platform_payload.externalPlatformId,
        dateStartFact=payload.factual_display_start_date,
        dateEndFact=payload.factual_display_end_date,
        dateStartPlan=payload.planned_display_start_date,
        dateEndPlan=payload.planned_display_end_date,
        viewsCountByFact=str(payload.factual_impressions),
        viewsCountByInvoice=str(payload.planned_impressions),
        moneySpent=format_decimal(payload.service_amount),
        unitCost=format_decimal(payload.unit_price_with_vat),
        withNds=False,
        comment=f"Imported from Google Sheets row {row.row_number}",
    )


def build_external_platform_id(channel_url: str) -> str:
    parsed = urlparse(channel_url)
    normalized = f"{parsed.netloc}{parsed.path}".strip("/").lower()
    digest = hashlib.sha1(channel_url.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "_", normalized)
    slug = "_".join(part for part in slug.split("_") if part) or "platform"
    return f"{slug}_{digest}"[:120]


def build_external_statistic_id(
    creative_id: str,
    external_platform_id: str,
    display_start_date: date,
    display_end_date: date,
) -> str:
    digest_source = (
        f"{creative_id}|{external_platform_id}|"
        f"{display_start_date.isoformat()}|{display_end_date.isoformat()}"
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    return f"stat_{creative_id}_{display_start_date.isoformat()}_{digest}"[:120]


def build_platform_name(channel_url: str) -> str:
    parsed = urlparse(channel_url)
    path = parsed.path.strip("/")
    if path:
        return path.split("/")[-1]
    return parsed.netloc


def format_decimal(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(normalized, "f")


def payloads_to_json(payloads: list[OzonOrdPayload], limit: int = 3) -> str:
    data = [asdict(payload) for payload in payloads[:limit]]
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def platform_payloads_to_json(
    payloads: list[OzonOrdPlatformPayload], limit: int = 3
) -> str:
    data = [asdict(payload) for payload in payloads[:limit]]
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def statistic_payloads_to_json(
    payloads: list[OzonOrdStatisticPayload], limit: int = 3
) -> str:
    data = [asdict(payload) for payload in payloads[:limit]]
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def admin_statistic_payloads_to_json(
    payloads: list[OzonOrdAdminStatisticPayload], limit: int = 3
) -> str:
    data = [asdict(payload) for payload in payloads[:limit]]
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
