from typing import Optional

import pytesseract
from pytesseract import Output

from app.services.ocr.base import BaseOCREngine, OCRResult
from app.services.ocr.preprocessing import preprocess


class TesseractEngine(BaseOCREngine):
    """
    Free, fast, no GPU needed — but weak on handwriting. Kept as a fallback
    for typed/printed text pages (e.g. printed question papers uploaded
    alongside handwritten answers) and as a cheap secondary opinion.
    """

    name = "tesseract"

    def extract(self, image_path: str, attempt: int = 1, hint: Optional[str] = None) -> OCRResult:
        img = preprocess(image_path, attempt=attempt)
        data = pytesseract.image_to_data(img, output_type=Output.DICT)

        words, confs = [], []
        for word, conf in zip(data["text"], data["conf"]):
            word = word.strip()
            if word:
                words.append(word)
                try:
                    c = float(conf)
                    if c >= 0:
                        confs.append(c / 100.0)
                except ValueError:
                    pass

        text = " ".join(words)
        avg_conf = sum(confs) / len(confs) if confs else 0.0

        return OCRResult(text=text, confidence=round(avg_conf, 3), engine=self.name, meta={"attempt": attempt})
