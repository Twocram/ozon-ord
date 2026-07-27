from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from ozon_ord_sync.application.sheet_parser import filter_rows_for_processing
from ozon_ord_sync.domain.mapping import build_statistic_payload
from ozon_ord_sync.domain.models import ParsedRow


def row(display_date: date | None) -> ParsedRow:
    return ParsedRow(
        row_number=5,
        manager="m",
        month=date(2026, 6, 1),
        platform="p",
        creative_id="creative",
        channel_url="https://t.me/test",
        executor="100б",
        contractor="c",
        price_with_tax=Decimal("100"),
        publication_date=date(2026, 6, 2),
        display_date=display_date,
        reach=10,
        mark=None,
        error=None,
        raw={},
    )


class StatisticPayloadMappingTest(unittest.TestCase):
    def test_skips_not_applicable_creative(self) -> None:
        source = replace(row(None), executor="100б", creative_id=" К/А ")

        self.assertEqual(filter_rows_for_processing([source]), [])

    def test_temporarily_accepts_every_executor(self) -> None:
        source = replace(row(None), executor="другой исполнитель")

        self.assertEqual(filter_rows_for_processing([source]), [source])

    def test_clamps_cross_month_display_end_to_publication_month_end(self) -> None:
        payload = build_statistic_payload(row(date(2026, 7, 3)))

        self.assertEqual(payload.dateStartFact, date(2026, 6, 2))
        self.assertEqual(payload.dateEndFact, date(2026, 6, 30))


if __name__ == "__main__":
    unittest.main()
