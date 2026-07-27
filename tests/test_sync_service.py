from __future__ import annotations

import unittest
from datetime import date

from ozon_ord_sync.application.sync_service import (
    extract_duplicate_statistic_row_numbers,
    extract_statistic_creation_errors,
    resolve_creative_ids,
    resolve_platform_ids,
)
from ozon_ord_sync.domain.models import (
    OzonOrdAdminStatisticPayload,
    ResolvedStatisticPayload,
)


class EntityResolutionTest(unittest.TestCase):
    def test_matches_telegram_channel_to_ord_post_url(self) -> None:
        client = type(
            "Client",
            (),
            {
                "list_platforms_page": lambda self, **kwargs: {
                    "platform": [
                        {
                            "url": "https://t.me/BSWEEDY_ONE/1095",
                            "platformId": "10041332",
                            "externalId": "ord-platform",
                        }
                    ]
                    if not kwargs["cursor_external_id"]
                    else []
                }
            },
        )()

        found, errors = resolve_platform_ids(
            client,
            {"sheet-platform": "https://t.me/bsweedy_one"},
        )

        self.assertEqual(found, {"sheet-platform": "10041332"})
        self.assertEqual(errors, [])

    def test_matches_creative_marker_case_insensitively_when_unique(self) -> None:
        client = type(
            "Client",
            (),
            {
                "list_creatives": lambda self, **kwargs: {
                    "creative": [
                        {
                            "marker": "2W5zFHDUwBo",
                            "creativeId": "4872499",
                            "externalCreativeId": "ord-creative",
                        }
                    ]
                    if not kwargs["cursor_external_id"]
                    else []
                }
            },
        )()

        found, errors = resolve_creative_ids(client, ["2W5zFHDUWBo"])

        self.assertEqual(found, {"2W5zFHDUWBo": "4872499"})
        self.assertEqual(errors, [])


class DuplicateStatisticErrorTest(unittest.TestCase):
    def test_maps_validation_duplicate_to_row_and_writes_details(self) -> None:
        resolved = [
            ResolvedStatisticPayload(
                row_number=12,
                payload=OzonOrdAdminStatisticPayload(
                    creativeId="4872843",
                    platformId="10736169",
                    price={},
                    comment="",
                    dateEndFact=date(2026, 6, 30),
                    dateEndPlan=date(2026, 6, 30),
                    paymentType="PAYMENT_TYPE_OTHER",
                    dateStartFact=date(2026, 6, 1),
                    dateStartPlan=date(2026, 6, 1),
                    unitCost="1",
                    viewsCountByFact="1",
                    viewsCountByInvoice="1",
                    sameDate=True,
                    sameViews=True,
                    isAutoCalc=True,
                    isSelfPromo=False,
                    isNative=False,
                    externalId="",
                    fromDate="",
                    toDate="",
                ),
            )
        ]
        message = (
            "Ошибка валидации\n"
            " - Продублирована статистика для креатива: 4872843 и площадки: "
            "10736169 за данный месяц: 2026-06, тип РК: Иное, акт: 0, договор: 0"
        )

        self.assertEqual(extract_duplicate_statistic_row_numbers(message, resolved), [12])
        self.assertEqual(
            extract_statistic_creation_errors(message, resolved),
            [
                "Row 12: Дубль статистики: креатив 4872843, площадка 10736169, месяц 2026-06"
            ],
        )


if __name__ == "__main__":
    unittest.main()
