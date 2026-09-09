"""
Gemini vision OCR engine.

Reuses the same google-genai SDK + GEMINI_API_KEY already used for grading.
Gemini is multimodal, so it transcribes a full handwritten page directly —
no line segmentation and no model weights to download. It is markedly
stronger on cursive / messy handwriting than Tesseract or TrOCR, which makes
it the recommended default engine here.

Set OCR_ENGINE=gemini in .env to use it (the default). The model is
configurable via OCR_GEMINI_MODEL (a "flash" model is plenty for
transcription and is cheaper/faster than the grading "pro" model).
"""
import logging
import os
from typing import Optional

from google import genai
from google.genai import types

from app.config import settings
from app.services.ocr.base import BaseOCREngine, OCRResult

logger = logging.getLogger(__name__)

_TRANSCRIBE_PROMPT = (
    "You are an OCR engine. Transcribe ALL handwritten (or printed) text in "
    "this image exactly as written, preserving line breaks and the original "
    "spelling. Do NOT correct spelling or grammar. Do NOT add any commentary, "
    "headings, or explanation. If a word is genuinely unreadable, write "
    "[illegible] in its place. Return only the transcribed text."
)

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _mime_for(path: str) -> str:
    return _MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), "image/png")


class GeminiOCREngine(BaseOCREngine):
    """Full-page handwriting OCR via the multimodal Gemini API."""

    name = "gemini"
    _client: Optional[genai.Client] = None

    def __init__(self, model: Optional[str] = None):
        self.model = model or settings.OCR_GEMINI_MODEL
        if GeminiOCREngine._client is None:
            if not settings.GEMINI_API_KEY:
                logger.warning("GEMINI_API_KEY is not set — Gemini OCR will fail until it is provided.")
            GeminiOCREngine._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def extract(self, image_path: str, attempt: int = 1, hint: Optional[str] = None) -> OCRResult:
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except OSError as exc:
            logger.error("Could not read image %s: %s", image_path, exc)
            return OCRResult(text="", confidence=0.0, engine=self.name, meta={"error": f"read_failed: {exc}"})

        prompt = _TRANSCRIBE_PROMPT
        if hint:
            prompt += f"\n\nThe student noted this about the page: {hint}"

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=image_bytes, mime_type=_mime_for(image_path)),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.0,       # deterministic transcription
                    max_output_tokens=2048,
                ),
            )
            text = (response.text or "").strip()
            usage_metadata = getattr(response, "usage_metadata", None)
            token_usage = {
                "input_tokens": getattr(usage_metadata, "prompt_token_count", 0) or 0,
                "output_tokens": getattr(usage_metadata, "candidates_token_count", 0) or 0,
                "thoughts_tokens": getattr(usage_metadata, "thoughts_token_count", 0) or 0,
                "total_tokens": getattr(usage_metadata, "total_token_count", 0) or 0,
            }
        except Exception as exc:  # network error, bad/missing key, quota, etc.
            logger.error("Gemini OCR request failed: %s", exc)
            return OCRResult(text="", confidence=0.0, engine=self.name, meta={"error": str(exc)})

        # Gemini does not return a numeric OCR confidence. Treat a real
        # transcription as high-confidence; an empty result as zero, which lets
        # the pipeline's fallback / low-confidence handling take over.
        confidence = 0.9 if text else 0.0
        return OCRResult(
            text=text,
            confidence=confidence,
            engine=self.name,
            meta={"model": self.model, "attempt": attempt, **token_usage},
        )
