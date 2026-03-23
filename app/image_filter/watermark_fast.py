from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np


@dataclass(frozen=True)
class WatermarkResult:
    ok: bool
    score: float
    reason: str


def detect_text_like_regions(image_path: str | Path,
                             edge_threshold: float = 0.08,
                             corner_weight: float = 1.6) -> WatermarkResult:
    """Fast heuristic text/watermark detection (no OCR).

    Goal: reject images that likely contain text/watermarks/links.

    Strategy (cheap):
    - Downscale
    - Canny edges
    - Measure edge density in regions where watermarks usually appear
      (corners + bottom strip)

    Returns ok=False when text is likely.
    """
    p = str(image_path)
    img = cv2.imread(p, cv2.IMREAD_COLOR)
    if img is None:
        return WatermarkResult(ok=False, score=1.0, reason="cannot_read_image")

    h, w = img.shape[:2]
    scale = 512 / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    edges = cv2.Canny(gray, 80, 160)
    edges = edges.astype(np.float32) / 255.0

    H, W = edges.shape[:2]

    def region(y0, y1, x0, x1) -> float:
        r = edges[y0:y1, x0:x1]
        if r.size == 0:
            return 0.0
        return float(r.mean())

    # Regions: corners and bottom strip
    c = int(min(H, W) * 0.18)
    bottom_h = int(H * 0.22)

    score_tl = region(0, c, 0, c)
    score_tr = region(0, c, W - c, W)
    score_bl = region(H - c, H, 0, c)
    score_br = region(H - c, H, W - c, W)
    score_bottom = region(H - bottom_h, H, 0, W)

    corner_score = max(score_tl, score_tr, score_bl, score_br)

    # Combine: corners are more suspicious
    combined = max(score_bottom, corner_score * corner_weight)

    if combined >= edge_threshold:
        return WatermarkResult(ok=False, score=combined, reason="text_like_edges")
    return WatermarkResult(ok=True, score=combined, reason="clean")
