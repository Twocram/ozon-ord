from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.infrastructure.document_text import extract_document_text

ACT_TEXT = (
    "Акт сдачи-приемки оказанных услуг\n"
    "г. Москва «20» мая 2026 года.\n"
    "Индивидуальный предприниматель Синицин Николай Дмитриевич оказал услуги "
    "по размещению рекламных материалов в телеграм канале автора.\n"
    "Итоги: 7 778"
)
# What a scanner app embeds instead of a text layer: stray glyphs, one per line.
GARBLED_TEXT = "\n".join("S = т Ф о т 1 0 л ю".split() * 40)


class ExtractDocumentTextTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.pdf = Path(directory.name) / "document.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 not a real pdf")

    def _extract(self, layer_text: str, recognised_text: str = "") -> tuple[str, MagicMock]:
        ocr = MagicMock(return_value=recognised_text)
        with (
            patch(
                "ozon_ord_sync.infrastructure.document_text.extract_pdf_text",
                return_value=layer_text,
            ),
            patch("ozon_ord_sync.infrastructure.document_text.ocr_pdf", ocr),
        ):
            return extract_document_text(self.pdf, "application/pdf"), ocr

    def test_keeps_a_readable_text_layer(self) -> None:
        text, ocr = self._extract(ACT_TEXT)

        self.assertEqual(text, ACT_TEXT)
        ocr.assert_not_called()

    def test_recognises_pages_of_a_scan_wrapped_in_a_pdf(self) -> None:
        text, ocr = self._extract("", ACT_TEXT)

        self.assertEqual(text, ACT_TEXT)
        ocr.assert_called_once()

    def test_recognises_pages_when_the_text_layer_is_stray_glyphs(self) -> None:
        text, ocr = self._extract(GARBLED_TEXT, ACT_TEXT)

        self.assertEqual(text, ACT_TEXT)
        ocr.assert_called_once()

    def test_recognises_pages_when_the_text_layer_mixes_alphabets(self) -> None:
        # A scanner app with a broken character map: plenty of words, but they are
        # Cyrillic with Latin letters spliced in, so no regex can read the number.
        garbled_layer = (
            "Щоговор оказания рекламных услуг Nэ 080б2026/3\n"
            "flоговор заключен в г. Москва, канrLпах указанных в Прило;кенttи ЛЪl\n"
        ) * 20

        text, ocr = self._extract(garbled_layer, ACT_TEXT)

        self.assertEqual(text, ACT_TEXT)
        ocr.assert_called_once()

    def test_keeps_the_text_layer_when_recognition_reads_even_less(self) -> None:
        text, _ = self._extract(GARBLED_TEXT, "Ф")

        self.assertEqual(text, GARBLED_TEXT)

    def test_an_image_is_recognised_directly(self) -> None:
        image = self.pdf.with_name("receipt.png")
        image.write_bytes(b"\x89PNG\r\n")
        with patch(
            "ozon_ord_sync.infrastructure.document_text.ocr_image",
            return_value=ACT_TEXT,
        ) as ocr_image:
            self.assertEqual(extract_document_text(image, "image/png"), ACT_TEXT)
        ocr_image.assert_called_once()


if __name__ == "__main__":
    unittest.main()
