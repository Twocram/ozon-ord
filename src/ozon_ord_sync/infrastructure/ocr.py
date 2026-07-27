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


def ocr_image(path: Path) -> str:
    if sys.platform != "darwin" or shutil.which("swift") is None:
        raise OcrError("OCR needs macOS Swift/Vision on this machine")

    with tempfile.NamedTemporaryFile("w", suffix=".swift", encoding="utf-8") as script:
        script.write(SWIFT_VISION_OCR)
        script.flush()
        result = subprocess.run(
            ["swift", script.name, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )

    if result.returncode != 0:
        raise OcrError(result.stderr.strip() or "OCR failed")
    return result.stdout.strip()
