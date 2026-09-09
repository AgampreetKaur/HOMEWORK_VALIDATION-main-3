"""
Simple projection-profile based line segmentation.

TrOCR expects individual line images, not a full page. This does a
lightweight horizontal-projection segmentation to crop the page into
lines before handing each one to the model. It's not as robust as a
dedicated layout model (e.g. Detectron-based), but works well for the
fairly uniform layout of a handwritten answer sheet and keeps the
pipeline free of extra heavy dependencies.

Robustness notes (why it isn't a plain global-Otsu projection):
  - A phone photo of a notebook page usually has bleed-through from the
    reverse side, ruled lines, uneven lighting and dark margins. A single
    global threshold marks all of that as "ink", so the gaps between lines
    vanish and the whole page collapses into one or two giant "lines".
  - We therefore (1) subtract a blurred copy of the page to keep only
    locally-dark ink, (2) use a sensible row cutoff instead of a near-zero
    one, and (3) trim each line to its ink columns so margins aren't fed to
    the recognizer.
"""
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image


def segment_lines(
    pil_img: Image.Image,
    min_line_height: int = 12,
    row_thresh_frac: float = 0.12,
    pad: int = 4,
) -> List[Tuple[Image.Image, Tuple[int, int, int, int]]]:
    """Split a handwritten page into single-line crops.

    Args:
        pil_img: the (already preprocessed) page image.
        min_line_height: ignore detected bands shorter than this many pixels.
        row_thresh_frac: a row counts as text if its ink fraction exceeds
            this fraction of the busiest row. Lower it (e.g. 0.09) to split
            more aggressively; raise it if tall lines get split in two.
        pad: pixels of padding added around each crop.

    Returns:
        A list of (line_image, (x0, y0, x1, y1)) in top-to-bottom order.
    """
    gray = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2GRAY)

    # (1) Remove bleed-through / uneven lighting BEFORE thresholding: subtract
    #     a heavily blurred copy so only locally-dark ink survives.
    blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=max(15, gray.shape[0] // 25))
    ink = cv2.subtract(blur, gray)
    _, binary = cv2.threshold(ink, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    # Horizontal projection: fraction of ink per row, lightly smoothed so a
    # single faint row within a line doesn't split it.
    row_frac = binary.mean(axis=1) / 255.0
    row_frac = np.convolve(row_frac, np.ones(5) / 5, mode="same")

    # (2) A sensible cutoff. A near-zero cutoff on a noisy page makes almost
    #     every row count as text and collapses the page into one band.
    threshold = max(row_frac.max() * row_thresh_frac, 0.01)

    h, w = binary.shape
    lines: List[Tuple[int, int]] = []
    in_line = False
    start = 0

    for y in range(h):
        is_text_row = row_frac[y] > threshold
        if is_text_row and not in_line:
            in_line = True
            start = y
        elif not is_text_row and in_line:
            in_line = False
            end = y
            if end - start >= min_line_height:
                lines.append((start, end))

    if in_line and (h - start) >= min_line_height:
        lines.append((start, h))

    # Crop each line from the ORIGINAL (natural grayscale/antialiased) image so
    # the recognizer sees real strokes, not a harsh binary — but use the ink
    # mask to (3) trim to the horizontal ink extent, dropping the dark left
    # margin and the blank right side.
    original = np.array(pil_img.convert("RGB"))
    results: List[Tuple[Image.Image, Tuple[int, int, int, int]]] = []

    for (start, end) in lines:
        y0 = max(0, start - pad)
        y1 = min(h, end + pad)

        cols = np.where(binary[y0:y1].any(axis=0))[0]
        if cols.size == 0:
            continue
        x0 = max(0, int(cols.min()) - pad)
        x1 = min(w, int(cols.max()) + pad)

        crop = original[y0:y1, x0:x1]
        results.append((Image.fromarray(crop), (x0, y0, x1, y1)))

    return results