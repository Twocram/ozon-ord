from __future__ import annotations

import json
from dataclasses import asdict

from ozon_ord_sync.domain.models import (
    OzonOrdAdminStatisticPayload,
    OzonOrdPayload,
    OzonOrdPlatformPayload,
    OzonOrdStatisticPayload,
)


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
