from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OCRResult:
    text: str
    confidence: float  # 0.0 - 1.0
    engine: str
    meta: dict = field(default_factory=dict)


class BaseOCREngine(ABC):
    """
    All OCR engines must implement this interface so the pipeline can
    swap engines (or fall back from one to another) without touching
    the rest of the app.
    """

    name: str = "base"

    @abstractmethod
    def extract(self, image_path: str, attempt: int = 1, hint: Optional[str] = None) -> OCRResult:
        """
        Run OCR on a single image and return extracted text + confidence.
        `attempt` lets an engine vary its strategy on rescans (e.g. heavier
        preprocessing on attempt 2+). `hint` is an optional student note
        about what went wrong on the previous attempt.
        """
        raise NotImplementedError
