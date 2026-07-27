from __future__ import annotations

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.sheet_parser import parse_document_check_sheet
from ozon_ord_sync.application.sync_workflows import run_document_check_preview


class DocumentCheckSheetParserTest(unittest.TestCase):
    def test_parses_document_check_rows(self) -> None:
        header = [
            "Дата заявки",
            "Менеджер",
            "Сумма платежа",
            "Описание расхода",
            "Договор ",
            "Счет ",
            "Контрагент",
            "Как подписано",
            "Статус Опаты",
            "Чеки/Акты",
            "Мес расхода",
            "Площадка",
            "Комментарий",
            "В ОРД",
            "ДОП.Соглашение",
        ]
        rows = [[
            "28.04.2026 17:45:55",
            "Бузаева Ульяна",
            "6\xa0540,00",
            "реклама",
            "https://drive.google.com/contract",
            "",
            "СЗ Дорофеева",
            "Скан",
            "Оплачено",
            "https://drive.google.com/act",
            "Май",
            "Телеграм",
            "",
            "FALSE",
            "",
        ]]

        with patch(
            "ozon_ord_sync.application.sheet_parser.fetch_sheet_rows",
            return_value=(header, rows),
        ):
            normalized_header, parsed_rows = parse_document_check_sheet("sheet")

        self.assertEqual(normalized_header[0], "submitted_at")
        self.assertEqual(len(parsed_rows), 1)
        row = parsed_rows[0]
        self.assertEqual(row.submitted_at, datetime(2026, 4, 28, 17, 45, 55))
        self.assertEqual(row.payment_amount, Decimal("6540.00"))
        self.assertEqual(row.counterparty, "СЗ Дорофеева")
        self.assertEqual(row.platform, "Телеграм")
        self.assertFalse(row.in_ord)

    def test_preview_returns_sample_rows(self) -> None:
        with patch(
            "ozon_ord_sync.application.sync_workflows.parse_document_check_sheet",
            return_value=([], []),
        ):
            result = run_document_check_preview("sheet", limit=1)

        self.assertTrue(result.ok)
        self.assertEqual(result.rows_parsed, 0)
        self.assertEqual(result.sample_rows, [])


if __name__ == "__main__":
    unittest.main()
