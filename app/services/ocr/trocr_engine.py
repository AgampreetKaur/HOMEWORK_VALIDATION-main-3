"""
TrOCR (Microsoft) handwriting OCR engine.

Why TrOCR: it's a transformer-based OCR model trained specifically on
handwritten text (IAM Handwriting dataset), it's fully open-source and
free to self-host (Apache 2.0 / MIT depending on checkpoint), and it
consistently outperforms Tesseract on messy handwriting. Runs on CPU
(slow) or GPU (fast) via HuggingFace `transformers`.

Model checkpoint: microsoft/trocr-large-handwritten
(swap to trocr-base-handwritten for a lighter/faster CPU-friendly option)
"""
import logging
from typing import Optional

import torch
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

from app.services.ocr.base import BaseOCREngine, OCRResult
from app.services.ocr.preprocessing import preprocess
from app.services.ocr.line_segmentation import segment_lines

logger = logging.getLogger(__name__)


class TrOCREngine(BaseOCREngine):
    name = "trocr"

    _processor = None
    _model = None
    _device = "cuda" if torch.cuda.is_available() else "cpu"

    def __init__(self, checkpoint: str = "microsoft/trocr-large-handwritten"):
        self.checkpoint = checkpoint
        self._load_model()

    @classmethod
    def _load_model(cls):
        # Loaded once per process and reused across requests — this is the
        # expensive part (model weights), so keep it as a class-level singleton.
        if cls._processor is None or cls._model is None:
            logger.info("Loading TrOCR model (%s) on %s ...", "microsoft/trocr-large-handwritten", cls._device)
            cls._processor = TrOCRProcessor.from_pretrained("microsoft/trocr-large-handwritten")
            cls._model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-large-handwritten")
            cls._model.to(cls._device)
            cls._model.eval()

    def _run_line(self, line_img: Image.Image) -> tuple[str, float]:
        pixel_values = self._processor(images=line_img, return_tensors="pt").pixel_values.to(self._device)
        with torch.no_grad():
            generated = self._model.generate(
                pixel_values,
                output_scores=True,
                return_dict_in_generate=True,
                max_length=256,
            )
        text = self._processor.batch_decode(generated.sequences, skip_special_tokens=True)[0]

        # Real per-token confidence. NOTE: with greedy decoding,
        # `generated.sequences_scores` is None, so the old proxy always fell
        # back to 0.7 (rescans never triggered). compute_transition_scores
        # gives per-token log-probs even for greedy decoding; we average the
        # token probabilities into a 0-1 confidence.
        try:
            trans = self._model.compute_transition_scores(
                generated.sequences, generated.scores, normalize_logits=True
            )
            probs = trans[0].exp()
            probs = probs[torch.isfinite(probs)]
            confidence = float(probs.mean()) if probs.numel() else 0.0
        except Exception:
            confidence = 0.7  # neutral default if scores are unavailable

        return text.strip(), round(confidence, 3)

    def extract(self, image_path: str, attempt: int = 1, hint: Optional[str] = None) -> OCRResult:
        preprocessed_img = preprocess(image_path, attempt=attempt)

        # TrOCR is a line-level recognizer, not a full-page model — a full
        # handwritten page must be segmented into lines first, then each
        # line is transcribed and stitched back together in order.
        lines = segment_lines(preprocessed_img)

        if not lines:
            return OCRResult(text="", confidence=0.0, engine=self.name, meta={"reason": "no_lines_detected"})

        transcribed_lines = []
        confidences = []
        for line_img, bbox in lines:
            text, conf = self._run_line(line_img)
            if text:
                transcribed_lines.append(text)
                confidences.append(conf)

        full_text = "\n".join(transcribed_lines)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            text=full_text,
            confidence=round(avg_confidence, 3),
            engine=self.name,
            meta={"line_count": len(lines), "attempt": attempt},
        )
