from __future__ import annotations

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from itertools import islice
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.receipt_parser import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    DOCUMENT_TYPE_ACT,
    DOCUMENT_TYPE_RECEIPT,
    document_type_error,
    extract_person_name,
    is_numberless_act_form,
    parse_receipt_text,
    receipt_id_candidates,
    resolve_receipt_id,
    self_employed_receipt_number_error,
    self_employed_receipt_number_is_valid,
    verify_receipt_number,
)


class ReceiptParserTest(unittest.TestCase):
    def test_extracts_number_and_numeric_date_from_long_act_title(self) -> None:
        receipt = parse_receipt_text(
            "Акт выполненных работ и оказанных услуг № 1 от 11.06.2026"
        )

        self.assertEqual(receipt.document_type, DOCUMENT_TYPE_ACT)
        self.assertEqual(receipt.receipt_number, "1")
        self.assertEqual(receipt.issued_at, datetime(2026, 6, 11))

    def test_extracts_number_from_act_title_with_description(self) -> None:
        receipt = parse_receipt_text("Акт об оказании услуг № 289 от 01 июня 2026 г.")

        self.assertEqual(receipt.receipt_number, "289")
        self.assertEqual(receipt.issued_at, datetime(2026, 6, 1))

    def test_extracts_act_date_written_in_the_contract_style(self) -> None:
        receipt = parse_receipt_text(
            "Акт сдачи-приемки оказанных услуг\nг. Москва «8» июля 2026 года."
        )

        self.assertEqual(receipt.issued_at, datetime(2026, 7, 8))

    def test_extracts_date_with_the_year_glued_to_a_cyrillic_suffix(self) -> None:
        for heading, day in (
            ("Акт No1 от «05.06.2026г.»", 5),
            ("Акт № 1 от 05.06.2026г.", 5),
            ("Акт No 12 от «7.6.26г.»", 7),
        ):
            receipt = parse_receipt_text(heading)

            self.assertEqual(receipt.issued_at, datetime(2026, 6, day), heading)
            self.assertIsNotNone(receipt.receipt_number, heading)

    def test_extracts_iso_date(self) -> None:
        receipt = parse_receipt_text("Акт номер A-7 от 2026-05-07")

        self.assertEqual(receipt.receipt_number, "A-7")
        self.assertEqual(receipt.issued_at, datetime(2026, 5, 7))

    def test_extracts_act_fields_from_pdf_text(self) -> None:
        receipt = parse_receipt_text(
            "\n".join(
                [
                    "Акт № 24 от 30 апреля 2026 г.",
                    "Итого к оплате: 13 900,00",
                    "Всего оказано услуг на сумму 13 900,00 руб.",
                    "ИНН 027882233142",
                ]
            )
        )

        self.assertEqual(receipt.document_type, DOCUMENT_TYPE_ACT)
        self.assertEqual(receipt.receipt_number, "24")
        self.assertEqual(receipt.issued_at, datetime(2026, 4, 30, 0, 0, 0))
        self.assertEqual(receipt.total_amount, Decimal("13900.00"))
        self.assertEqual(receipt.inns, ["027882233142"])

    def test_extracts_lknpd_receipt_fields(self) -> None:
        receipt = parse_receipt_text(
            "\n".join(
                [
                    "Чек Nº20h5m6quym",
                    "30.04.26",
                    "23:59(+03:00)",
                    "Матовников Кирилл Юрьевич",
                    "Наименование",
                    "Итого:",
                    "18 900,00 ₽",
                    "Режим НО",
                    "ИНН",
                    "НПД",
                    "480210039013",
                ]
            ),
            "https://lknpd.nalog.ru/api/v1/receipt/480210039013/20h5m6quym/print",
        )

        self.assertEqual(receipt.document_type, DOCUMENT_TYPE_RECEIPT)
        self.assertEqual(receipt.receipt_number, "20h5m6quym")
        self.assertEqual(receipt.issued_at, datetime(2026, 4, 30, 23, 59))
        self.assertEqual(receipt.seller_name, "Матовников Кирилл Юрьевич")
        self.assertEqual(receipt.total_amount, Decimal("18900.00"))

    def test_extracts_receipt_fields_from_ocr_text(self) -> None:
        receipt = parse_receipt_text(
            "\n".join(
                [
                    "ЧЕК",
                    "Чек Nº 200x773xqk",
                    "30.04.2026 19:38:09(+03:00),",
                    "Режим НО: НПД",
                    "ДОРОФЕЕВА",
                    "АЛИСА МИХАЙЛОВНА",
                    "Наименование услуг",
                    "Сумма",
                    "6 540,00 ₽",
                    "Итого",
                    "6 540,00 ₽",
                    "ИНН",
                    "503116774789",
                ]
            )
        )

        self.assertEqual(receipt.document_type, DOCUMENT_TYPE_RECEIPT)
        self.assertEqual(receipt.receipt_number, "200x773xqk")
        self.assertEqual(receipt.issued_at, datetime(2026, 4, 30, 19, 38, 9))
        self.assertEqual(receipt.seller_name, "ДОРОФЕЕВА АЛИСА МИХАЙЛОВНА")
        self.assertEqual(receipt.total_amount, Decimal("6540.00"))
        self.assertEqual(receipt.inns, ["503116774789"])

    def test_keeps_labels_out_of_the_seller_name(self) -> None:
        # OCR puts "Режим НО" above the ФИО; the old line-based parser glued the
        # label into the name and the contract check then failed.
        receipt = parse_receipt_text(
            "\n".join(
                [
                    "Чек Nº 200x773xqk",
                    "Режим НО: НПД",
                    "ДОРОФЕЕВА АЛИСА МИХАЙЛОВНА",
                    "Наименование услуг",
                    "6 540,00 ₽",
                ]
            ),
            "https://lknpd.nalog.ru/api/v1/receipt/503116774789/200x773xqk/print",
        )

        self.assertEqual(receipt.seller_name, "ДОРОФЕЕВА АЛИСА МИХАЙЛОВНА")
        self.assertEqual(receipt.seller_name_confidence, CONFIDENCE_HIGH)


class ReceiptNumberTest(unittest.TestCase):
    def test_prefers_receipt_id_from_lknpd_link_over_ocr(self) -> None:
        # OCR read the digit 1 as the letter l; the link carries the real id.
        receipt = parse_receipt_text(
            "Чек Nº200vlohcgi\n15.05.26\n23:59(+03:00)",
            "https://lknpd.nalog.ru/api/v1/receipt/780261278113/200v1ohcgi/print",
        )

        self.assertEqual(receipt.receipt_number, "200v1ohcgi")

    def test_joins_receipt_id_split_by_pdf_layout(self) -> None:
        for heading, expected in (
            ("Чек Nº2008miu7 nc", "2008miu7nc"),
            ("Чек Nº204 qnobrie", "204qnobrie"),
            ("Чек Nº200 8mi u7nc", "2008miu7nc"),
            ("Чек Nº2008miu7 пс", "2008miu7nc"),  # OCR read the tail as Cyrillic
        ):
            receipt = parse_receipt_text(f"{heading}\n15.05.26\n23:59(+03:00)")

            self.assertEqual(receipt.receipt_number, expected, heading)

    def test_leaves_act_numbers_untouched(self) -> None:
        for heading, expected in (
            ("Акт № 204 qnobrie от 11.06.2026", "204"),  # acts are never joined
            ("Акт № 15-РК от 11.06.2026", "15-РК"),  # Cyrillic is legitimate here
            ("Чек № 204 от 15.05.26", "204"),
            ("Чек № 204 от 15 05 2026", "204"),
        ):
            self.assertEqual(
                parse_receipt_text(heading).receipt_number,
                expected,
                heading,
            )

    def test_repairs_cyrillic_look_alikes_inside_receipt_id(self) -> None:
        receipt = parse_receipt_text("ЧЕК\nЧек Nº 201b2rcриx\n15.05.2026 23:59:59(+03:00),")

        self.assertEqual(receipt.receipt_number, "201b2rcpux")

    def test_leaves_act_numbers_alone(self) -> None:
        self.assertEqual(
            parse_receipt_text("Акт № 204 ok от 11.06.2026").receipt_number,
            "204",
        )
        self.assertEqual(
            parse_receipt_text("Чек № б/н от 11.06.2026").receipt_number,
            "б/н",
        )


class NumberlessActTest(unittest.TestCase):
    """"Акт сдачи-приемки оказанных услуг": a title, a date, and no number at all."""

    ACT = "\n".join([
        "Акт сдачи-приемки оказанных услуг",
        "г. Москва «20 » мая 2026 года.",
        "Общество с ограниченной ответственностью “100балльный репетитор” (ООО “100балльный",
        "репетитор», в лице генерального директора Золотухина Александра Михайловича",
        "Индивидуальный предприниматель Синицин Николай Дмитриевич, действующий на основании",
        "ОГРНИП 326710000006478, именуемый в дальнейшем «Исполнитель»",
        "Итоги: 7 778",
    ])

    def test_reads_the_date_typed_with_stray_spaces_in_quotes(self) -> None:
        receipt = parse_receipt_text(self.ACT)

        self.assertEqual(receipt.document_type, DOCUMENT_TYPE_ACT)
        self.assertEqual(receipt.issued_at, datetime(2026, 5, 20))
        self.assertIsNone(receipt.receipt_number)

    def test_marks_the_form_as_numberless(self) -> None:
        self.assertTrue(parse_receipt_text(self.ACT).number_optional)
        self.assertTrue(is_numberless_act_form("Акт приёма-передачи оказанных услуг"))

    def test_other_act_forms_still_need_a_number(self) -> None:
        for heading in (
            "Акт № 7 от 30 мая 2026 г.",
            "Акт об оказании услуг от 30 мая 2026 г.",
            "Универсальный передаточный документ",
        ):
            self.assertFalse(parse_receipt_text(heading).number_optional, heading)


class TransferDocumentTest(unittest.TestCase):
    """УПД: an act merged with a счёт-фактура, its number far from the heading."""

    def test_reads_number_and_date_from_the_invoice_line(self) -> None:
        receipt = parse_receipt_text(
            "\n".join([
                "Универсальный",
                "передаточный",
                "документ",
                "Счет-фактура № 31 от 26 мая 2026 г. (1) Исправление № -- от -- (1а)",
                "Приложение № 1 к постановлению Правительства Российской Федерации "
                "от 26 декабря 2011 г. № 1137",
                "Продавец: ИП Маликов Никита Олегович (2)",
                "Всего к оплате (9) 10 500,00 Х-- 10 500,00",
            ])
        )

        self.assertEqual(receipt.document_type, DOCUMENT_TYPE_ACT)
        self.assertEqual(receipt.receipt_number, "31")
        self.assertEqual(receipt.issued_at, datetime(2026, 5, 26))

    def test_reads_an_invoice_line_below_the_heading(self) -> None:
        receipt = parse_receipt_text(
            "\n".join([
                "Универсальный",
                "передаточный",
                "документ",
                "Статус: 1 – счет-фактура и",
                "передаточный",
                "документ (акт)",
                "Приложение № 1 к постановлению Правительства Российской Федерации "
                "от 26 декабря 2011 г. № 1137",
                "Счет-фактура № 10260527001 от 27 мая 2026 г. (1) Исправление № -- от -- (1а)",
                "Документ об отгрузке Универсальный передаточный документ, "
                "№ 10260527001 от 27.05.2026 (5а)",
            ])
        )

        self.assertEqual(receipt.document_type, DOCUMENT_TYPE_ACT)
        self.assertEqual(receipt.receipt_number, "10260527001")
        self.assertEqual(receipt.issued_at, datetime(2026, 5, 27))

    def test_ignores_blank_form_fields(self) -> None:
        receipt = parse_receipt_text(
            "\n".join([
                "Универсальный передаточный документ",
                "К счету-фактуре (счетам-фактурам), выставленному при получении оплаты",
                "№ от , исправление № от (5б)",
                "Счет-фактура № 7 от 30 мая 2026 г. (1) Исправление № -- от -- (1а)",
            ])
        )

        self.assertEqual(receipt.receipt_number, "7")
        self.assertEqual(receipt.issued_at, datetime(2026, 5, 30))

    def test_an_act_referring_to_an_invoice_keeps_its_own_number_and_date(self) -> None:
        receipt = parse_receipt_text(
            "Акт № 7 от 30 мая 2026 г.\nОснование: Счет-фактура № 99 от 01 января 2026 г."
        )

        self.assertEqual(receipt.receipt_number, "7")
        self.assertEqual(receipt.issued_at, datetime(2026, 5, 30))


class ReceiptIdVerificationTest(unittest.TestCase):
    def test_asks_lknpd_about_the_id_as_read_first(self) -> None:
        probes: list[str] = []

        def exists(inn: str, receipt_id: str) -> bool:
            probes.append(receipt_id)
            return receipt_id == "204qno6rie"

        confirmed, answered = resolve_receipt_id(
            "330711573550", "204qnobrie", exists=exists
        )

        self.assertEqual((confirmed, answered), ("204qno6rie", True))
        self.assertEqual(probes[0], "204qnobrie")

    def test_tries_a_systematic_misread_before_single_characters(self) -> None:
        # A font renders l as 1 everywhere it appears, so both ones of
        # "203x109k10" are really the letter l — that reading has to come early.
        candidates = list(islice(receipt_id_candidates("203x109k10"), 8))

        self.assertEqual(candidates[0], "203x109k10")
        self.assertIn("203xl09kl0", candidates)

    def test_resolves_a_misread_repeated_twice(self) -> None:
        probes: list[str] = []

        def exists(inn: str, receipt_id: str) -> bool:
            probes.append(receipt_id)
            return receipt_id == "203xl09kl0"

        confirmed, answered = resolve_receipt_id(
            "231215332411", "203x109k10", exists=exists
        )

        self.assertEqual((confirmed, answered), ("203xl09kl0", True))
        self.assertLessEqual(len(probes), 8)

    def test_keeps_the_reading_when_lknpd_is_unreachable(self) -> None:
        self.assertEqual(
            resolve_receipt_id("330711573550", "204qnobrie", exists=lambda *_: None),
            (None, False),
        )

    def test_fixes_a_misread_receipt_number(self) -> None:
        receipt = parse_receipt_text("Чек Nº204qnobrie\n15.05.26\nИНН\n330711573550")

        with patch(
            "ozon_ord_sync.application.receipt_parser.receipt_exists",
            side_effect=lambda inn, receipt_id: receipt_id == "204qno6rie",
        ):
            verify_receipt_number(receipt)

        self.assertEqual(receipt.receipt_number, "204qno6rie")
        self.assertTrue(receipt.receipt_number_verified)

    def test_reports_a_number_lknpd_does_not_know(self) -> None:
        receipt = parse_receipt_text("Чек Nº204qnobrie\n15.05.26\nИНН\n330711573550")

        with patch(
            "ozon_ord_sync.application.receipt_parser.receipt_exists",
            return_value=False,
        ):
            verify_receipt_number(receipt)

        self.assertIs(receipt.receipt_number_verified, False)
        self.assertEqual(receipt.receipt_number, "204qnobrie")

    def test_does_not_check_acts_or_documents_without_inn(self) -> None:
        for text in (
            "Акт № 115 от 18 мая 2026 г.\nИНН 330711573550",  # not a ЛК НПД receipt
            "Чек Nº204qnobrie\n15.05.26",  # no ИНН to ask about
        ):
            exists = MagicMock()
            with patch(
                "ozon_ord_sync.application.receipt_parser.receipt_exists",
                exists,
            ):
                receipt = verify_receipt_number(parse_receipt_text(text))

            exists.assert_not_called()
            self.assertIsNone(receipt.receipt_number_verified, text)


class PersonNameExtractionTest(unittest.TestCase):
    def test_reads_performer_name_from_act_and_skips_customer_director(self) -> None:
        name, confidence = extract_person_name(
            "\n".join(
                [
                    "Акт № 24 от 30 апреля 2026 г.",
                    "Исполнитель: ИП Дорофеева Алиса Михайловна, ИНН 503116774789",
                    "Заказчик: ООО «100балльный репетитор» в лице",
                    "Генерального директора Смирнова Игоря Петровича",
                ]
            )
        )

        self.assertEqual(name, "Дорофеева Алиса Михайловна")
        self.assertEqual(confidence, CONFIDENCE_HIGH)

    def test_reads_surname_with_initials(self) -> None:
        name, confidence = extract_person_name(
            "АКТ № 7 от 01.06.2026\nИсполнитель\nИП Иванов И.И.\nЗаказчик\nООО Ромашка"
        )

        self.assertEqual(name, "Иванов И. И.")
        self.assertEqual(confidence, CONFIDENCE_HIGH)

    def test_reads_name_split_across_lines(self) -> None:
        name, _ = extract_person_name("Режим НО: НПД\nДОРОФЕЕВА\nАЛИСА МИХАЙЛОВНА\nИтого")

        self.assertEqual(name, "ДОРОФЕЕВА АЛИСА МИХАЙЛОВНА")

    def test_two_word_name_is_low_confidence_without_label(self) -> None:
        name, confidence = extract_person_name("Акт № 1\nИванов Иван\n100,00 руб.")

        self.assertEqual(name, "Иванов Иван")
        self.assertEqual(confidence, CONFIDENCE_LOW)

    def test_returns_nothing_for_all_caps_document_without_name(self) -> None:
        self.assertEqual(
            extract_person_name(
                "АКТ № 24 ОТ 30 АПРЕЛЯ 2026 Г.\n"
                "ВСЕГО ОКАЗАНО УСЛУГ НА СУММУ 13 900,00 РУБ.\n"
                "ИТОГО К ОПЛАТЕ: 13 900,00"
            ),
            (None, None),
        )


class SelfEmployedReceiptTest(unittest.TestCase):
    def test_validates_self_employed_receipt_number(self) -> None:
        self.assertTrue(
            self_employed_receipt_number_is_valid(
                "self_employed",
                DOCUMENT_TYPE_RECEIPT,
                "200x773xqk",
            )
        )
        for number in (None, "123456", "abcdef"):
            self.assertFalse(
                self_employed_receipt_number_is_valid(
                    "self_employed",
                    DOCUMENT_TYPE_RECEIPT,
                    number,
                )
            )
        self.assertIsNone(
            self_employed_receipt_number_is_valid(
                "entrepreneur",
                DOCUMENT_TYPE_ACT,
                "24",
            )
        )
        self.assertEqual(
            self_employed_receipt_number_error(
                "self_employed",
                DOCUMENT_TYPE_RECEIPT,
                "123456",
            ),
            "Ошибка: номер чека самозанятого должен содержать буквы и цифры",
        )

    def test_reports_wrong_document_for_performer_status(self) -> None:
        self.assertEqual(
            document_type_error("self_employed", DOCUMENT_TYPE_ACT),
            "Ошибка: для самозанятого в «Чеки/Акты» должен быть чек",
        )
        self.assertEqual(
            document_type_error("entrepreneur", DOCUMENT_TYPE_RECEIPT),
            "Ошибка: для ИП в «Чеки/Акты» должен быть акт",
        )


if __name__ == "__main__":
    unittest.main()
