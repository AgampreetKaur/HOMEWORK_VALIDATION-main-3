"""
Server-side Gemini text-generation proxy.

Generic prompt-in, text-out endpoint used for test-paper and MCQ
generation. The frontend builds the full prompt and sends it here rather
than calling Gemini directly, so the API key never needs to exist in the
browser — it is read from GEMINI_API_KEY in .env, the same key used for
OCR/grading/report-card analysis.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.auth import get_current_user
from app.usage_models import TokenUsageLog
from app.usage_pricing import estimate_cost_usd, PRICING


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["generate"])

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY is not set — /generate will fail until it is provided.")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


DEFAULT_MODEL = "gemini-3.6-flash"

# Only ever use a model we actually have a price for (see usage_pricing.py) —
# stops a client from passing an arbitrary/expensive model string.
_ALLOWED_MODELS = set(PRICING.keys())


class GenerateIn(BaseModel):
    prompt: str
    model: Optional[str] = None


class GenerateOut(BaseModel):
    text: str


@router.post("", response_model=GenerateOut)
def generate_text(
    payload: GenerateIn,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.prompt or not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt must not be empty.")

    model = payload.model if payload.model in _ALLOWED_MODELS else DEFAULT_MODEL

    client = _get_client()

    try:
        response = client.models.generate_content(
            model=model,
            contents=payload.prompt,
            config=types.GenerateContentConfig(temperature=0),
        )
    except Exception as exc:
        logger.error("Generation request failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Generation request failed: {exc}")

    text = response.text or ""

    # Actual token usage reported by Gemini, not an estimate.
    usage_metadata = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage_metadata, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage_metadata, "candidates_token_count", 0) or 0
    thoughts_tokens = getattr(usage_metadata, "thoughts_token_count", 0) or 0
    total_tokens = getattr(usage_metadata, "total_token_count", 0) or 0

    source = "test_generator_student" if current_user.get("role") == "student" else "test_generator_parent"

    try:
        db.add(TokenUsageLog(
            source=source,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
            total_tokens=total_tokens,
            cost_usd=estimate_cost_usd(model, input_tokens, output_tokens, thoughts_tokens),
        ))
        db.commit()
    except Exception:
        logger.exception("Failed to write token usage log for /generate")
        db.rollback()

    return GenerateOut(text=text)
