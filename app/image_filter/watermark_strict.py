from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class OCRResult:
    ok: bool
    text: str
    reason: str


_BAD_PATTERNS = [
    re.compile(r"@\w+"),
    re.compile(r"https?://"),
    re.compile(r"\bt\.me\b"),
    re.compile(r"\bwww\.[a-z0-9\-]+\.[a-z]{2,}\b", re.I),
    re.compile(r"\b[a-z0-9\-]+\.(com|net|org|ru|ua|io|gg|app|me|cc)\b", re.I),
    re.compile(r"pinterest", re.I),
]


def ocr_and_check(image_path: str | Path) -> OCRResult:
    """Strict mode: OCR the image and reject if it contains '@' / links / domains.

    Requires pytesseract and installed tesseract binary.
    If pytesseract is not installed, returns ok=True with reason 'ocr_unavailable'.
    """
    try:
        import pytesseract  # type: ignore
    except Exception:
        return OCRResult(ok=True, text="", reason="ocr_unavailable")

    img = Image.open(str(image_path)).convert("RGB")

    # Pytesseract config: treat as a single uniform block
    text = pytesseract.image_to_string(img, config="--psm 6")
    clean = " ".join(text.split())

    for pat in _BAD_PATTERNS:
        if pat.search(clean):
            return OCRResult(ok=False, text=clean, reason=f"matched:{pat.pattern}")

    # If OCR found a lot of text, also reject (high risk)
    if len(clean) >= 24:
        return OCRResult(ok=False, text=clean, reason="ocr_text_detected")

    return OCRResult(ok=True, text=clean, reason="clean")
