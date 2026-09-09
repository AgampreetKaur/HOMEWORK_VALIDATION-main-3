import logging
from typing import Optional

from app.config import settings
from app.services.ocr.base import BaseOCREngine, OCRResult

logger = logging.getLogger(__name__)

_engine_instance: Optional[BaseOCREngine] = None


def get_ocr_engine() -> BaseOCREngine:
    """
    Returns a singleton OCR engine instance based on settings.OCR_ENGINE.
    Kept as a singleton because TrOCR's model weights are expensive to load.
    """
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance

    if settings.OCR_ENGINE == "gemini":
        from app.services.ocr.gemini_engine import GeminiOCREngine
        _engine_instance = GeminiOCREngine()
    elif settings.OCR_ENGINE == "trocr":
        from app.services.ocr.trocr_engine import TrOCREngine
        _engine_instance = TrOCREngine()
    elif settings.OCR_ENGINE == "tesseract":
        from app.services.ocr.tesseract_engine import TesseractEngine
        _engine_instance = TesseractEngine()
    else:
        raise ValueError(f"Unknown OCR_ENGINE: {settings.OCR_ENGINE}")

    return _engine_instance


def run_ocr(image_path: str, attempt: int = 1, hint: Optional[str] = None) -> OCRResult:
    engine = get_ocr_engine()
    result = engine.extract(image_path, attempt=attempt, hint=hint)

    # Safety net: if the primary handwriting engine returns nothing useful,
    # (e.g. a blank/near-blank page, or a printed page it struggled with)
    # try Tesseract as a cheap secondary pass rather than failing outright.
    if not result.text.strip() and engine.name != "tesseract":
        try:
            from app.services.ocr.tesseract_engine import TesseractEngine
            fallback = TesseractEngine()
            fallback_result = fallback.extract(image_path, attempt=attempt, hint=hint)
            if fallback_result.text.strip():
                fallback_result.meta["primary_engine_failed"] = engine.name
                return fallback_result
        except Exception as exc:
            # e.g. the Tesseract system binary is not installed. Never let the
            # optional fallback turn an empty result into a hard error.
            logger.warning("Tesseract fallback unavailable/failed: %s", exc)

    return result
