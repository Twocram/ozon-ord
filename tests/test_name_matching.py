from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.name_matching import (
    name_contains,
    name_key,
    names_match,
    normalize_name,
)


class NamesMatchTest(unittest.TestCase):
    def test_ignores_case_and_yo(self) -> None:
        self.assertTrue(names_match("ФЁДОРОВА АЛЁНА ИВАНОВНА", "Федорова Алена Ивановна"))

    def test_matches_declined_contract_name(self) -> None:
        self.assertTrue(
            names_match("Дорофеевой Алисы Михайловны", "ДОРОФЕЕВА АЛИСА МИХАЙЛОВНА")
        )
        self.assertTrue(
            names_match("Матовникова Кирилла Юрьевича", "Матовников Кирилл Юрьевич")
        )

    def test_repairs_latin_homoglyphs_from_ocr(self) -> None:
        # OCR turned Cyrillic Е into Latin E and О into Latin O.
        self.assertTrue(names_match("ДОРОФEEВА АЛИСА МИХАЙЛOВНА", "Дорофеева Алиса Михайловна"))

    def test_matches_initials_against_full_name(self) -> None:
        self.assertTrue(names_match("Иванов И.И.", "Иванов Иван Иванович"))
        self.assertTrue(names_match("Иванов И. И.", "иванов иван иванович"))

    def test_ignores_word_order(self) -> None:
        self.assertTrue(names_match("Алиса Михайловна Дорофеева", "Дорофеева Алиса Михайловна"))

    def test_rejects_different_people(self) -> None:
        self.assertFalse(names_match("Иванов Иван Иванович", "Петров Иван Иванович"))
        self.assertFalse(names_match("Иванов И.И.", "Иванов Алексей Петрович"))
        self.assertFalse(names_match("Дорофеева Алиса", "Матовников Кирилл"))

    def test_undecidable_without_full_tokens(self) -> None:
        self.assertIsNone(names_match(None, "Иванов Иван Иванович"))
        self.assertIsNone(names_match("", "Иванов Иван Иванович"))
        self.assertIsNone(names_match("И.И.", "Иванов Иван Иванович"))
        # Only noise words: legal form, no name.
        self.assertIsNone(names_match("ИП", "Иванов Иван Иванович"))


class NameContainsTest(unittest.TestCase):
    def test_ignores_legal_form_and_month_from_sheet(self) -> None:
        for counterparty in (
            "СЗ Дорофеева ИЮНЬ",
            "сз дорофеева",
            "ИП Дорофеева (телеграм) май",
            "ДОРОФЕЕВА",
        ):
            self.assertTrue(
                name_contains(counterparty, "Дорофеева Алиса Михайловна"),
                counterparty,
            )

    def test_rejects_other_counterparty(self) -> None:
        self.assertFalse(name_contains("СЗ Петров", "Дорофеева Алиса Михайловна"))

    def test_undecidable_without_names(self) -> None:
        self.assertIsNone(name_contains("СЗ ИЮНЬ", "Дорофеева Алиса Михайловна"))
        self.assertIsNone(name_contains("СЗ Дорофеева", None))


class NormalizeNameTest(unittest.TestCase):
    def test_lowercases_and_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_name("  ДОРОФЕЕВА\n АЛЁНА  "), "дорофеева алена")

    def test_name_key_is_case_and_order_independent(self) -> None:
        self.assertEqual(
            name_key("СЗ ДОРОФЕЕВА АЛИСА МИХАЙЛОВНА"),
            name_key("Михайловна Дорофеева Алиса"),
        )


if __name__ == "__main__":
    unittest.main()
