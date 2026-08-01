from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class OcrError(RuntimeError):
    pass


SWIFT_VISION_OCR = r'''
import Foundation
import Vision
import AppKit

let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path)
guard let image = NSImage(contentsOf: url),
      let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cgImage = bitmap.cgImage else {
  fputs("cannot load image\n", stderr)
  exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ru-RU", "en-US"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
  try handler.perform([request])
  for observation in request.results ?? [] {
    if let text = observation.topCandidates(1).first?.string {
      print(text)
    }
  }
} catch {
  fputs("\(error)\n", stderr)
  exit(1)
}
'''


SWIFT_PDF_OCR = r'''
import Foundation
import Vision
import AppKit
import PDFKit

let path = CommandLine.arguments[1]
guard let document = PDFDocument(url: URL(fileURLWithPath: path)) else {
  fputs("cannot load pdf\n", stderr)
  exit(1)
}

// Render at twice the page size: a scan of an act is unreadable for Vision at 72 dpi.
let scale: CGFloat = 2.0
for index in 0..<document.pageCount {
  guard let page = document.page(at: index) else { continue }
  let bounds = page.bounds(for: .mediaBox)
  let size = NSSize(width: bounds.width * scale, height: bounds.height * scale)
  guard let tiff = page.thumbnail(of: size, for: .mediaBox).tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiff),
        let cgImage = bitmap.cgImage else { continue }

  let request = VNRecognizeTextRequest()
  request.recognitionLevel = .accurate
  request.recognitionLanguages = ["ru-RU", "en-US"]
  request.usesLanguageCorrection = true

  let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
  do {
    try handler.perform([request])
    for observation in request.results ?? [] {
      if let text = observation.topCandidates(1).first?.string {
        print(text)
      }
    }
  } catch {
    fputs("\(error)\n", stderr)
    exit(1)
  }
}
'''


def ocr_image(path: Path) -> str:
    return _run_vision(SWIFT_VISION_OCR, path)


def ocr_pdf(path: Path) -> str:
    """Read a PDF that carries no text layer by recognising its rendered pages."""
    return _run_vision(SWIFT_PDF_OCR, path)


def _run_vision(swift_source: str, path: Path) -> str:
    if sys.platform != "darwin" or shutil.which("swift") is None:
        raise OcrError("OCR needs macOS Swift/Vision on this machine")

    with tempfile.NamedTemporaryFile("w", suffix=".swift", encoding="utf-8") as script:
        script.write(swift_source)
        script.flush()
        result = subprocess.run(
            ["swift", script.name, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )

    if result.returncode != 0:
        raise OcrError(result.stderr.strip() or "OCR failed")
    return result.stdout.strip()
