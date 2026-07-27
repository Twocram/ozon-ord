from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.vat_checker import (
    VAT_CHARGED,
    VAT_NOT_CHARGED,
    detect_vat_status,
    vat_check_note,
    vat_rate,
)


class VatStatusTest(unittest.TestCase):
    def test_detects_charged_vat(self) -> None:
        for text in (
            "НДС включен",
            "НДС включён",
            "В том числе НДС",
            "НДС 20%",
            "НДС 5%",
            "НДС по ставке 20 %",
            "Стоимость услуг с учётом НДС",
            "20% НДС",
        ):
            self.assertEqual(detect_vat_status(text), VAT_CHARGED, text)

    def test_detects_vat_that_is_not_charged(self) -> None:
        for text in (
            "Без НДС",
            "НДС не облагается",
            "НДС не начисляется",
            "не облагается НДС",
            "Без налога (НДС)",
            "Исполнитель не является плательщиком НДС",
            "Освобождён от уплаты НДС",
            "НДС 0%",
        ):
            self.assertEqual(detect_vat_status(text), VAT_NOT_CHARGED, text)

    def test_treats_a_table_header_with_an_empty_value_as_not_charged(self) -> None:
        # Real act: "В том числе НДС" is a column header, "Без НДС" is its value.
        self.assertEqual(detect_vat_status("В том числе НДС Без НДС"), VAT_NOT_CHARGED)
        self.assertNotEqual(detect_vat_status("В том числе НДС: 0,00"), VAT_CHARGED)
        self.assertEqual(
            detect_vat_status("Итого 23 200, в том числе НДС 20% - 3 866,67"),
            VAT_CHARGED,
        )

    def test_silent_document_has_no_status(self) -> None:
        self.assertIsNone(detect_vat_status("Акт об оказании услуг № 1"))

    def test_charged_wins_over_not_charged_wording(self) -> None:
        # A contract that says both is exactly what a human should look at.
        self.assertEqual(
            detect_vat_status("Стоимость услуг НДС не облагается. В том числе НДС 20%"),
            VAT_CHARGED,
        )

    def test_reads_the_rate(self) -> None:
        self.assertEqual(vat_rate("НДС по ставке 20%"), Decimal("20"))
        self.assertEqual(vat_rate("НДС 5%"), Decimal("5"))
        self.assertIsNone(vat_rate("Без НДС"))


class VatCheckNoteTest(unittest.TestCase):
    def test_marks_the_row_when_vat_is_charged(self) -> None:
        self.assertEqual(
            vat_check_note("Стоимость услуг, в том числе НДС 20%", "Без НДС"),
            "НДС: в договоре ставка 20%. Проверьте вручную",
        )
        self.assertEqual(
            vat_check_note("Без НДС", "Сумма с НДС"),
            "НДС: в акте/чеке НДС включён. Проверьте вручную",
        )
        self.assertEqual(
            vat_check_note("НДС 5%", "НДС 5%"),
            "НДС: в договоре ставка 5%, в акте/чеке ставка 5%. Проверьте вручную",
        )

    def test_does_not_mark_rows_without_charged_vat(self) -> None:
        # These used to be reported as errors and kept the row out of ORD.
        for contract_text, receipt_text in (
            ("НДС не облагается", "Без НДС"),
            ("НДС не облагается", ""),
            ("", "Без НДС"),
            ("", ""),
            ("Исполнитель не является плательщиком НДС", "НДС 0%"),
        ):
            self.assertIsNone(
                vat_check_note(contract_text, receipt_text),
                (contract_text, receipt_text),
            )

    def test_skips_self_employed(self) -> None:
        self.assertIsNone(
            vat_check_note("НДС 20%", "НДС 20%", performer_status="self_employed")
        )


if __name__ == "__main__":
    unittest.main()
