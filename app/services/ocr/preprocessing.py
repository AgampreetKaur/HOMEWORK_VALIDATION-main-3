"""
Preprocessing pipeline for scanned/photographed handwritten pages.

Called before every OCR attempt. On rescans (attempt > 1) we apply
progressively more aggressive cleanup, since a plain re-run of the same
engine on the same pixels usually reproduces the same mistake.
"""
import cv2
import numpy as np
from PIL import Image


def _pil_to_cv(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def _cv_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def deskew(cv_img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bitwise_not(gray)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if coords.shape[0] < 10:
        return cv_img
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.5:
        return cv_img
    (h, w) = cv_img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(cv_img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def denoise_and_contrast(cv_img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def adaptive_binarize(cv_img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    binarized = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    return cv2.cvtColor(binarized, cv2.COLOR_GRAY2BGR)


def preprocess(image_path: str, attempt: int = 1) -> Image.Image:
    """
    attempt 1: light touch — deskew + contrast only, preserves handwriting texture
               that transformer OCR models are trained on.
    attempt 2: + denoise more aggressively.
    attempt 3+: + adaptive binarization as a last resort (can hurt handwriting
               OCR sometimes, hence only used on later retries).
    """
    img = Image.open(image_path)
    cv_img = _pil_to_cv(img)

    cv_img = deskew(cv_img)
    cv_img = denoise_and_contrast(cv_img)

    if attempt >= 3:
        cv_img = adaptive_binarize(cv_img)

    return _cv_to_pil(cv_img)
