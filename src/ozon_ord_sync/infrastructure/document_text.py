from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ozon_ord_sync.infrastructure.ocr import ocr_image, ocr_pdf


class DocumentTextError(RuntimeError):
    pass


_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{3,}")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_MIN_WORD_DENSITY = 4  # words of three letters or more per hundred characters
_MAX_MIXED_ALPHABET_SHARE = 3  # percent of words mixing Cyrillic with Latin


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
    if not _is_pdf(path, content_type):
        return ocr_image(path)

    text = extract_pdf_text(path)
    if _looks_reliable(text):
        return text

    # The text layer cannot be trusted, so read the rendered pages instead — and
    # keep that reading only if it is itself trustworthy, otherwise fall back to
    # whichever of the two carries more words.
    recognised = ocr_pdf(path)
    if _looks_reliable(recognised):
        return recognised
    return recognised if _word_count(recognised) > _word_count(text) else text


def _looks_reliable(text: str) -> bool:
    """Whether a reading of a PDF can be trusted.

    A text layer lies in two ways. A photo or a scan wrapped in a PDF carries no
    text at all, or stray glyphs — few words for a lot of characters. A scanner app
    with a broken character map produces words that mix alphabets ("flоговор",
    "Щоговор оказания услуг Nэ 080б2026/3"): readable to the eye, not to a regex.
    Real documents sit far from both limits — every one measured had no mixed words
    at all, while the two broken ones had 10% and 46%.
    """
    stripped = text.strip()
    if not stripped:
        return False
    words = _WORD_RE.findall(stripped)
    if len(words) * 100 < len(stripped) * _MIN_WORD_DENSITY:
        return False
    mixed = sum(1 for word in words if _mixes_alphabets(word))
    return mixed * 100 <= len(words) * _MAX_MIXED_ALPHABET_SHARE


def _mixes_alphabets(word: str) -> bool:
    return bool(_CYRILLIC_RE.search(word)) and bool(_LATIN_RE.search(word))


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


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
