from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.contract_channel_checker import (
    build_contract_channel_check_rows,
    extract_service_table_text,
    extract_telegram_links,
    mentions_telegram_authors,
)


class ContractChannelCheckerTest(unittest.TestCase):
    def test_extracts_only_service_table(self) -> None:
        text = "\n".join(
            [
                "Общая ссылка https://t.me/outside",
                "1. Исполнитель оказывает Заказчику следующие рекламные услуги:",
                "Телеграм канале автора, ссылка https://t.me/inside",
                "ИТОГО: 45000 руб.",
                "Другая ссылка https://t.me/after",
            ]
        )

        section = extract_service_table_text(text)

        self.assertIn("https://t.me/inside", section)
        self.assertNotIn("https://t.me/outside", section)
        self.assertNotIn("https://t.me/after", section)

    def test_returns_empty_text_without_service_table_heading(self) -> None:
        self.assertEqual(
            extract_service_table_text("Ссылка https://t.me/outside"),
            "",
        )

    def test_extracts_multiple_telegram_links(self) -> None:
        self.assertEqual(
            extract_telegram_links("канал https://t.me/one и https://t.me\n/two"),
            ["https://t.me/one", "https://t.me/two"],
        )

    def test_detects_authors_phrase(self) -> None:
        self.assertTrue(
            mentions_telegram_authors("в телеграм канале авторов: https://t.me/one")
        )
        self.assertTrue(mentions_telegram_authors("в телеграмм канале авторов"))
        self.assertTrue(mentions_telegram_authors("в телеграмм каналах авторов"))

    def test_one_unreadable_file_does_not_abort_other_rows(self) -> None:
        rows = [
            SimpleNamespace(row_number=2, contract_url="ok", receipts_acts_url=None),
            SimpleNamespace(row_number=3, contract_url="bad", receipts_acts_url=None),
        ]
        downloaded = SimpleNamespace(path=Path("ok.pdf"), content_type="application/pdf")
        contract_text = "\n".join(
            [
                "Исполнитель оказывает Заказчику следующие рекламные услуги:",
                "https://t.me/one https://t.me/two",
                "ИТОГО: 1 руб.",
            ]
        )

        with (
            patch(
                "ozon_ord_sync.application.contract_channel_checker.parse_document_check_sheet",
                return_value=([], rows),
            ),
            patch(
                "ozon_ord_sync.application.contract_channel_checker.download_drive_file",
                side_effect=[downloaded, ValueError("cannot load image")],
            ),
            patch(
                "ozon_ord_sync.application.contract_channel_checker.extract_document_text",
                return_value=contract_text,
            ),
        ):
            results = build_contract_channel_check_rows("sheet")

        self.assertEqual([row.row_number for row in results], [2, 3])
        self.assertEqual(results[0].value, "Проверьте вручную")
        self.assertEqual(
            results[1].value,
            "Ошибка проверки договора: cannot load image",
        )


if __name__ == "__main__":
    unittest.main()
