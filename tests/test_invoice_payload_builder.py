from __future__ import annotations

import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.invoice_payload_builder import (
    build_invoice_payload_drafts,
    row_skip_reason,
)
from ozon_ord_sync.domain.models import ParsedDocumentCheckRow


def document_check_row(**overrides: object) -> ParsedDocumentCheckRow:
    fields = {
        "row_number": 2,
        "submitted_at": datetime(2026, 4, 28, 17, 45, 55),
        "manager": "m",
        "payment_amount": Decimal("6540.00"),
        "expense_description": "ad",
        "contract_url": "contract-url",
        "invoice_url": None,
        "counterparty": "СЗ Дорофеева",
        "signature_type": "Скан",
        "payment_status": "Оплачено",
        "receipts_acts_url": "receipt-url",
        "expense_month": "Май",
        "platform": "Телеграм",
        "comment": None,
        "in_ord": False,
        "addendum_url": None,
        "check": None,
        "raw": {},
    }
    fields.update(overrides)
    return ParsedDocumentCheckRow(**fields)  # type: ignore[arg-type]


class InvoicePayloadBuilderTest(unittest.TestCase):
    def test_builds_payload_draft_from_sheet_receipt_and_contract(self) -> None:
        row = ParsedDocumentCheckRow(
            row_number=2,
            submitted_at=datetime(2026, 4, 28, 17, 45, 55),
            manager="m",
            payment_amount=Decimal("6540.00"),
            expense_description="ad",
            contract_url="contract-url",
            invoice_url=None,
            counterparty="СЗ Дорофеева",
            signature_type="Скан",
            payment_status="Оплачено",
            receipts_acts_url="receipt-url",
            expense_month="Май",
            platform="Телеграм",
            comment=None,
            in_ord=False,
            addendum_url=None,
            check=None,
            raw={},
        )

        def fake_download(url: str, target_dir: Path):
            path = target_dir / url
            path.write_text("", encoding="utf-8")
            return type("Downloaded", (), {"path": path, "content_type": "text/plain"})()

        def fake_text(path: Path, content_type: str | None = None) -> str:
            if path.name == "receipt-url":
                return "\n".join([
                    "Чек Nº 200x773xqk",
                    "30.04.2026 19:38:09(+03:00),",
                    "Режим НО: НПД",
                    "ДОРОФЕЕВА",
                    "АЛИСА МИХАЙЛОВНА",
                    "Наименование услуг",
                    "Итого",
                    "6 540,00 ₽",
                ])
            return "\n".join([
                "Договор оказания рекламных услуг № 27042026/21",
                "г. Москва 27 апреля 2026г.",
                "Общество с ограниченной ответственностью “100балльный репетитор”",
                "именуемое в дальнейшем «Заказчик», и Дорофеева Алиса Михайловна, зарегистрированный",
                "ИТОГО: 6540 руб.",
            ])

        with (
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.parse_document_check_sheet",
                return_value=([], [row]),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.download_drive_file",
                side_effect=fake_download,
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.extract_document_text",
                side_effect=fake_text,
            ),
        ):
            draft = build_invoice_payload_drafts("sheet")[0]

        self.assertEqual(draft.payload["invoiceNumber"], "200x773xqk")
        self.assertEqual(draft.payload["startDate"], "2026-05-01")
        self.assertEqual(draft.payload["endDate"], "2026-05-31")
        self.assertEqual(draft.payload["contractNumber"], "27042026/21")
        self.assertTrue(draft.checks["receipt_contract_name"])
        self.assertIn("payload missing: contractId", draft.issues)

    def test_name_checks_survive_case_declension_and_weak_ocr(self) -> None:
        row = ParsedDocumentCheckRow(
            row_number=3,
            submitted_at=datetime(2026, 4, 28, 17, 45, 55),
            manager="m",
            payment_amount=Decimal("6540.00"),
            expense_description="ad",
            contract_url="contract-url",
            invoice_url=None,
            counterparty="сз дорофеева МАЙ",
            signature_type="Скан",
            payment_status="Оплачено",
            receipts_acts_url="receipt-url",
            expense_month="Май",
            platform="Телеграм",
            comment=None,
            in_ord=False,
            addendum_url=None,
            check=None,
            raw={},
        )

        def fake_text(path: Path, content_type: str | None = None) -> str:
            if path.name == "receipt-url":
                # ALL CAPS OCR with a Latin E inside the surname.
                return "\n".join([
                    "Чек Nº 200x773xqk",
                    "30.04.2026 19:38:09(+03:00),",
                    "Режим НО: НПД",
                    "ДОРОФEЕВА АЛИСА МИХАЙЛОВНА",
                    "Наименование услуг",
                    "Итого",
                    "6 540,00 ₽",
                ])
            # The contract declines the ФИО.
            return "\n".join([
                "Договор оказания рекламных услуг № 27042026/21",
                "г. Москва 27 апреля 2026г.",
                "Общество с ограниченной ответственностью “100балльный репетитор”",
                "именуемое в дальнейшем «Заказчик», и Дорофеевой Алисы Михайловны, зарегистрированный",
                "ИТОГО: 6540 руб.",
            ])

        with (
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.parse_document_check_sheet",
                return_value=([], [row]),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.download_drive_file",
                side_effect=lambda url, target_dir: type(
                    "Downloaded",
                    (),
                    {"path": target_dir / url, "content_type": "text/plain"},
                )(),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.extract_document_text",
                side_effect=fake_text,
            ),
        ):
            draft = build_invoice_payload_drafts("sheet")[0]

        self.assertTrue(draft.checks["receipt_contract_name"])
        self.assertTrue(draft.checks["sheet_receipt_name"])
        self.assertTrue(draft.checks["sheet_contract_name"])

    def test_low_confidence_receipt_name_does_not_fail_the_row(self) -> None:
        row = ParsedDocumentCheckRow(
            row_number=4,
            submitted_at=datetime(2026, 4, 28, 17, 45, 55),
            manager="m",
            payment_amount=Decimal("6540.00"),
            expense_description="ad",
            contract_url="contract-url",
            invoice_url=None,
            counterparty="СЗ Дорофеева",
            signature_type="Скан",
            payment_status="Оплачено",
            receipts_acts_url="receipt-url",
            expense_month="Май",
            platform="Телеграм",
            comment=None,
            in_ord=False,
            addendum_url=None,
            check=None,
            raw={},
        )

        def fake_text(path: Path, content_type: str | None = None) -> str:
            if path.name == "receipt-url":
                # No ФИО in the act: the only name-shaped run is someone else,
                # picked by shape alone, so a mismatch must not block the row.
                return "\n".join([
                    "Акт № 1 от 30.04.2026",
                    "Смирнов Игорь",
                    "Итого к оплате: 6 540,00",
                ])
            return "\n".join([
                "Договор оказания рекламных услуг № 27042026/21",
                "г. Москва 27 апреля 2026г.",
                "Общество с ограниченной ответственностью “100балльный репетитор”",
                "именуемое в дальнейшем «Заказчик», и Дорофеева Алиса Михайловна, зарегистрированный",
                "ИТОГО: 6540 руб.",
            ])

        with (
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.parse_document_check_sheet",
                return_value=([], [row]),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.download_drive_file",
                side_effect=lambda url, target_dir: type(
                    "Downloaded",
                    (),
                    {"path": target_dir / url, "content_type": "text/plain"},
                )(),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.extract_document_text",
                side_effect=fake_text,
            ),
        ):
            draft = build_invoice_payload_drafts("sheet")[0]

        self.assertIsNone(draft.checks["receipt_contract_name"])
        self.assertIsNone(draft.checks["sheet_receipt_name"])
        self.assertNotIn("check failed: receipt_contract_name", draft.issues)

    def test_resolves_ord_contract_and_creatives(self) -> None:
        row = ParsedDocumentCheckRow(
            row_number=2,
            submitted_at=datetime(2026, 4, 28, 17, 45, 55),
            manager="m",
            payment_amount=Decimal("6540.00"),
            expense_description="ad",
            contract_url="contract-url",
            invoice_url=None,
            counterparty="СЗ Дорофеева ИЮНЬ",
            signature_type="Скан",
            payment_status="Оплачено",
            receipts_acts_url="receipt-url",
            expense_month="Май",
            platform="Телеграм",
            comment=None,
            in_ord=False,
            addendum_url=None,
            check=None,
            raw={},
        )
        client = type(
            "Client",
            (),
            {
                "list_contracts": lambda self, query: {
                    "contract": [
                        {
                            "id": "5469541",
                            "contractNumber": "27042026/21",
                            "contractDate": "2026-04-27",
                            "organisationCustomerId": "2332078",
                            "organisationPerformerId": "11278486",
                            "customer": {
                                "id": "2332078",
                                "title": "100балльный репетитор",
                                "organizationType": "LEGAL_TYPE_LEGAL",
                                "address": "",
                            },
                            "performer": {
                                "id": "11278486",
                                "title": "Дорофеева Алиса Михайловна",
                                "organizationType": "LEGAL_TYPE_INDIVIDUAL",
                                "address": "Москва",
                            },
                        }
                    ]
                },
                "list_admin_creatives": lambda self, query: {
                    "creative": [{"id": "4612917"}]
                },
            },
        )()

        with (
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.parse_document_check_sheet",
                return_value=([], [row]),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.download_drive_file",
                side_effect=lambda url, target_dir: type(
                    "Downloaded",
                    (),
                    {"path": target_dir / url, "content_type": "text/plain"},
                )(),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.extract_document_text",
                side_effect=lambda path, content_type=None: "\n".join(
                    [
                        "Чек Nº 200x773xqk" if path.name == "receipt-url" else "Договор оказания рекламных услуг № 27042026/21",
                        "30.04.2026 19:38:09(+03:00)," if path.name == "receipt-url" else "г. Москва 27 апреля 2026г.",
                        "Режим НО: НПД" if path.name == "receipt-url" else "Общество с ограниченной ответственностью “100балльный репетитор”",
                        "ДОРОФЕЕВА" if path.name == "receipt-url" else "именуемое в дальнейшем «Заказчик», и Дорофеева Алиса Михайловна, зарегистрированный",
                        "АЛИСА МИХАЙЛОВНА" if path.name == "receipt-url" else "ИТОГО: 6540 руб.",
                        "Наименование услуг" if path.name == "receipt-url" else "",
                        "Итого" if path.name == "receipt-url" else "",
                        "6 540,00 ₽" if path.name == "receipt-url" else "",
                        "Без НДС" if path.name == "receipt-url" else "НДС не облагается",
                    ]
                ),
            ),
        ):
            draft = build_invoice_payload_drafts("sheet", admin_client=client)[0]

        self.assertTrue(draft.ok)
        self.assertEqual(draft.payload["contractId"], "5469541")
        self.assertEqual(draft.payload["performerId"], "11278486")
        self.assertEqual(
            draft.payload["contracts"][0]["creatives"],
            [{"creativeId": "4612917"}],
        )


class VatRowTest(unittest.TestCase):
    def test_charged_vat_is_noted_but_does_not_block_the_row(self) -> None:
        row = document_check_row(row_number=5, counterparty="ИП Иванов")

        def fake_text(path: Path, content_type: str | None = None) -> str:
            if path.name == "receipt-url":
                return "\n".join([
                    "Акт № 24 от 30 апреля 2026 г.",
                    "Исполнитель: ИП Иванов Иван Иванович",
                    "Итого к оплате: 6 540,00",
                    "В том числе НДС 20%: 1 090,00",
                ])
            return "\n".join([
                "Договор оказания рекламных услуг № 27042026/21",
                "г. Москва 27 апреля 2026г.",
                "Общество с ограниченной ответственностью “100балльный репетитор”",
                "именуемое в дальнейшем «Заказчик», и Индивидуальный предприниматель",
                "Иванов Иван Иванович, зарегистрированный, ОГРНИП 304500116000157",
                "ИТОГО: 6540 руб., в том числе НДС 20%",
            ])

        with (
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.parse_document_check_sheet",
                return_value=([], [row]),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.download_drive_file",
                side_effect=lambda url, target_dir: type(
                    "Downloaded",
                    (),
                    {"path": target_dir / url, "content_type": "text/plain"},
                )(),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.extract_document_text",
                side_effect=fake_text,
            ),
        ):
            draft = build_invoice_payload_drafts("sheet")[0]

        self.assertEqual(
            draft.vat_note,
            "НДС: в договоре ставка 20%, в акте/чеке ставка 20%. Проверьте вручную",
        )
        self.assertNotIn("contract_receipt_vat", draft.checks)
        self.assertFalse([issue for issue in draft.issues if "НДС" in issue])
        self.assertIsNotNone(draft.payload)

    def test_no_note_when_vat_is_not_charged(self) -> None:
        row = document_check_row(row_number=6, counterparty="ИП Иванов")

        def fake_text(path: Path, content_type: str | None = None) -> str:
            if path.name == "receipt-url":
                return "Акт № 24 от 30 апреля 2026 г.\nБез НДС\nИтого к оплате: 6 540,00"
            return "\n".join([
                "Договор оказания рекламных услуг № 27042026/21",
                "г. Москва 27 апреля 2026г.",
                "именуемое в дальнейшем «Заказчик», и Индивидуальный предприниматель",
                "Иванов Иван Иванович, зарегистрированный",
                "ИТОГО: 6540 руб. НДС не облагается",
            ])

        with (
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.parse_document_check_sheet",
                return_value=([], [row]),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.download_drive_file",
                side_effect=lambda url, target_dir: type(
                    "Downloaded",
                    (),
                    {"path": target_dir / url, "content_type": "text/plain"},
                )(),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.extract_document_text",
                side_effect=fake_text,
            ),
        ):
            draft = build_invoice_payload_drafts("sheet")[0]

        self.assertIsNone(draft.vat_note)
        self.assertFalse([issue for issue in draft.issues if "НДС" in issue])


class SkippedRowTest(unittest.TestCase):
    def test_detects_console_and_edo_rows_regardless_of_case(self) -> None:
        for signature_type in ("Консоль", "консоль", "ПОДПИСАНО В КОНСОЛИ"):
            self.assertEqual(
                row_skip_reason(document_check_row(signature_type=signature_type)),
                f"«Как подписано»: {signature_type}",
            )
        for receipts_acts in ("В эдо подписан", "в ЭДО подписан", "в консоли"):
            self.assertEqual(
                row_skip_reason(document_check_row(receipts_acts_url=receipts_acts)),
                f"«Чеки/Акты»: {receipts_acts}",
            )

    def test_keeps_ordinary_rows(self) -> None:
        self.assertIsNone(row_skip_reason(document_check_row()))
        # "ЭДО" in «Как подписано» is a normal signing method: such rows do carry
        # an act and must still be registered.
        self.assertIsNone(
            row_skip_reason(
                document_check_row(
                    signature_type="ЭДО",
                    receipts_acts_url="https://drive.google.com/file/d/1/view",
                )
            )
        )

    def test_skipped_rows_are_not_read_or_registered(self) -> None:
        rows = [
            document_check_row(row_number=2, signature_type="КОНСОЛЬ"),
            document_check_row(row_number=3, receipts_acts_url="В ЭДО подписан"),
        ]
        download = MagicMock()

        with (
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.parse_document_check_sheet",
                return_value=([], rows),
            ),
            patch(
                "ozon_ord_sync.application.invoice_payload_builder.download_drive_file",
                download,
            ),
        ):
            drafts = build_invoice_payload_drafts("sheet")

        download.assert_not_called()
        self.assertEqual(
            [draft.skip_reason for draft in drafts],
            ["«Как подписано»: КОНСОЛЬ", "«Чеки/Акты»: В ЭДО подписан"],
        )
        for draft in drafts:
            self.assertFalse(draft.ok)
            self.assertEqual(draft.issues, [])
            self.assertIsNone(draft.payload)


if __name__ == "__main__":
    unittest.main()
