from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.sheet_parser import parse_creative_sheet
from ozon_ord_sync.application.sync_workflows import run_creative_preview


class CreativeSheetParserTest(unittest.TestCase):
    def test_parses_raw_creative_rows(self) -> None:
        header = [
            "ссылка на канал ",
            "название канала",
            "ссылка на договор",
            "ссылка на фото поста",
            " текст поста",
            "Название креатива ",
            "целевые ссылки поста",
            "Форма распространения рекламы ",
        ]
        rows = [
            [
                "https://t.me/allenstorieslee",
                "за объективом",
                "https://drive.google.com/file/d/contract/view",
                "https://drive.google.com/file/d/photo/view",
                "Текст поста",
                "июль/шалапайка/Адиля/подписки/ИП Копанев",
                "https://t.me/addlist/one https://t.me/addlist/two",
                "текстово-графический блок",
            ]
        ]

        with patch(
            "ozon_ord_sync.application.sheet_parser.fetch_sheet_rows",
            return_value=(header, rows),
        ):
            normalized_header, parsed_rows = parse_creative_sheet("sheet")

        self.assertEqual(len(normalized_header), 8)
        self.assertEqual(len(parsed_rows), 1)
        row = parsed_rows[0]
        self.assertEqual(row.row_number, 2)
        self.assertEqual(row.raw["channel_url"], "https://t.me/allenstorieslee")
        self.assertEqual(row.raw["nazvanie_kanala"], "за объективом")
        self.assertEqual(
            row.raw["nazvanie_kreativa"],
            "июль/шалапайка/Адиля/подписки/ИП Копанев",
        )

    def test_skips_effectively_empty_rows(self) -> None:
        header = ["ссылка на канал", "название канала"]
        rows = [["", ""], ["https://t.me/a", "b"]]

        with patch(
            "ozon_ord_sync.application.sheet_parser.fetch_sheet_rows",
            return_value=(header, rows),
        ):
            _, parsed_rows = parse_creative_sheet("sheet")

        self.assertEqual(len(parsed_rows), 1)
        self.assertEqual(parsed_rows[0].row_number, 3)


class CreativePreviewWorkflowTest(unittest.TestCase):
    def test_preview_returns_header_and_sample_rows(self) -> None:
        with patch(
            "ozon_ord_sync.application.sync_workflows.parse_creative_sheet",
            return_value=([], []),
        ):
            result = run_creative_preview("sheet", limit=1)

        self.assertTrue(result.ok)
        self.assertEqual(result.rows_parsed, 0)
        self.assertEqual(result.sample_rows, [])


if __name__ == "__main__":
    unittest.main()
