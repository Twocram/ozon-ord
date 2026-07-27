from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.contract_parser import (
    PERFORMER_STATUS_ENTREPRENEUR,
    PERFORMER_STATUS_SELF_EMPLOYED,
    parse_contract_text,
)


class ContractParserTest(unittest.TestCase):
    def test_extracts_contract_fields(self) -> None:
        contract = parse_contract_text(
            "\n".join(
                [
                    "Договор оказания рекламных услуг № 27042026/21",
                    "г. Москва 27 апреля 2026г.",
                    "Общество с ограниченной ответственностью “100балльный репетитор” (ООО",
                    "именуемое в дальнейшем «Заказчик», и Дорофеева Алиса Михайловна , зарегистрированный",
                    "ИТОГО: 6540 руб.",
                ]
            )
        )

        self.assertEqual(contract.contract_number, "27042026/21")
        self.assertEqual(contract.contract_date, date(2026, 4, 27))
        self.assertEqual(contract.customer_name, "100балльный репетитор")
        self.assertEqual(contract.performer_name, "Дорофеева Алиса Михайловна")
        self.assertEqual(contract.total_amount, Decimal("6540"))

    def test_extracts_quoted_contract_date_before_later_dates(self) -> None:
        contract = parse_contract_text(
            "г. Москва «11» мая 2026 г.\nДата регистрации: 28 декабря 2024 г."
        )

        self.assertEqual(contract.contract_date, date(2026, 5, 11))


class PerformerStatusParserTest(unittest.TestCase):
    def test_detects_self_employed(self) -> None:
        contract = parse_contract_text(
            "Пешкова Светлана Владимировна, зарегистрированный в качестве "
            "самозанятого, являющийся плательщиком налога на профессиональный доход"
        )

        self.assertEqual(contract.performer_status, PERFORMER_STATUS_SELF_EMPLOYED)

    def test_detects_individual_entrepreneur(self) -> None:
        contract = parse_contract_text(
            "Индивидуальный предприниматель Некрылов Максим Юрьевич, ОГРНИП 123"
        )

        self.assertEqual(contract.performer_status, PERFORMER_STATUS_ENTREPRENEUR)


class PerformerInnParserTest(unittest.TestCase):
    def test_extracts_performer_inn_when_columns_are_interleaved(self) -> None:
        # PDFKit flattens the two-column table row-by-row: each line holds the
        # Заказчик value on the left and the Исполнитель value on the right.
        contract = parse_contract_text(
            "\n".join(
                [
                    "8. Реквизиты и подписи Сторон",
                    "Заказчик Исполнитель",
                    "ООО «100балльный репетитор» Индивидуальный предприниматель",
                    "Юридический адрес: 117638, Г.МОСКВА ОГРНИП: 324253600068527",
                    "МУНИЦИПАЛЬНЫЙ ОКРУГ ЗЮЗИНО ИНН: 254302252947",
                    'e-mail: help_ks@100points.ru Реквизиты в Банке: АО "АЛЬФА-БАНК"',
                    "ИНН 9721218842/ КПП 772701001 БИК: 044525593",
                ]
            )
        )

        self.assertEqual(contract.performer_inn, "254302252947")

    def test_extracts_performer_inn_when_columns_are_stacked(self) -> None:
        # PDFKit flattens the table column-by-column: the whole Заказчик block
        # first, then the whole Исполнитель block.
        contract = parse_contract_text(
            "\n".join(
                [
                    "8. Реквизиты и подписи Сторон",
                    "ООО «100балльный репетитор»",
                    "ИНН 9721218842/ КПП 772701001",
                    "ОГРН 1237700776037",
                    "Индивидуальный предприниматель Кузьменко Ольга Евгеньевна",
                    "ОГРНИП: 324253600068527",
                    "ИНН: 254302252947",
                ]
            )
        )

        self.assertEqual(contract.performer_inn, "254302252947")

    def test_returns_none_without_performer_inn(self) -> None:
        contract = parse_contract_text(
            "8. Реквизиты и подписи Сторон\nИНН 9721218842/ КПП 772701001"
        )

        self.assertIsNone(contract.performer_inn)


if __name__ == "__main__":
    unittest.main()
