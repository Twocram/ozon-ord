from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ozon_ord_sync.infrastructure.ocr import ocr_image, ocr_pdf


class DocumentTextError(RuntimeError):
    pass


SWIFT_PDF_TEXT = r'''
import Foundation
import PDFKit

let path = CommandLine.arguments[1]
guard let document = PDFDocument(url: URL(fileURLWithPath: path)) else {
  fputs("cannot load pdf\n", stderr)
  exit(1)
}
print(document.string ?? "")
'''


def extract_document_text(path: Path, content_type: str | None = None) -> str:
    if _is_pdf(path, content_type):
        text = extract_pdf_text(path)
        # A photo or a scan wrapped in a PDF has an empty text layer, which used to
        # leave the whole document unread. Recognise its pages instead.
        return text if text.strip() else ocr_pdf(path)
    return ocr_image(path)


def extract_pdf_text(path: Path) -> str:
    if sys.platform != "darwin" or shutil.which("swift") is None:
        raise DocumentTextError("PDF text extraction needs macOS Swift/PDFKit")

    with tempfile.NamedTemporaryFile("w", suffix=".swift", encoding="utf-8") as script:
        script.write(SWIFT_PDF_TEXT)
        script.flush()
        result = subprocess.run(
            ["swift", script.name, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )

    if result.returncode != 0:
        raise DocumentTextError(result.stderr.strip() or "PDF text extraction failed")
    return result.stdout.strip()


def _is_pdf(path: Path, content_type: str | None) -> bool:
    if content_type and content_type.split(";", 1)[0].strip().lower() == "application/pdf":
        return True
    try:
        return path.read_bytes()[:5] == b"%PDF-"
    except OSError:
        return False
