from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.infrastructure.telegram_bot import (
    extract_command_value,
    format_upload_result,
)


class ExtractCommandValueTest(unittest.TestCase):
    def test_extracts_token_from_set_token_command(self) -> None:
        self.assertEqual(
            extract_command_value("/set_token abc=123; sid=456"),
            "abc=123; sid=456",
        )

    def test_returns_empty_string_without_token(self) -> None:
        self.assertEqual(extract_command_value("/set_token"), "")


class FormatUploadResultTest(unittest.TestCase):
    def test_includes_resolution_errors(self) -> None:
        message = format_upload_result(
            {
                "ok": False,
                "resolution_errors": ["Platform not found", "Creative missing"],
            },
            400,
        )

        self.assertIn("❌ Ошибка при отправке статистики.", message)
        self.assertIn("Ошибки проверки данных:", message)
        self.assertIn("Платформа не найдена", message)

    def test_includes_success_warnings(self) -> None:
        message = format_upload_result(
            {
                "ok": True,
                "rows_eligible": 10,
                "statistics_prepared": 8,
                "ozon_response": {"skipped_errors": ["Row 2: Креатив уже есть в базе"]},
            },
            200,
        )

        self.assertIn("✅ Отправка статистики завершена.", message)
        self.assertIn("⚠️ Предупреждения:", message)
        self.assertIn("Строка 2: Креатив уже есть в базе", message)


if __name__ == "__main__":
    unittest.main()
