"""
Token usage logging.

Every Gemini call this backend makes (OCR in services/ocr/gemini_engine.py,
grading in services/grading/grader.py, generation in routers/generation.py)
writes one row here with the exact token counts and cost reported by
Gemini itself — not an estimate.

usage_metadata reports three counts: prompt_token_count (input_tokens),
candidates_token_count (output_tokens), and thoughts_token_count
(thoughts_tokens — internal reasoning tokens, billed at the output rate
but not included in candidates_token_count). total_tokens is Gemini's own
sum, kept for a sanity cross-check.

cost_usd is computed once at write time from usage_pricing.py and stored,
not recomputed later, so a future rate change doesn't rewrite historical
costs.

Note: report_analysis.py's Gemini calls are not yet logged here.
"""

from datetime import datetime

from sqlalchemy import Column, String, Integer, Float, DateTime

from app.database import Base
from app.models import gen_uuid


class TokenUsageLog(Base):
    __tablename__ = "token_usage_logs"

    id = Column(String, primary_key=True, default=gen_uuid)

    # "ocr" | "grading" — extend as you wire in more Gemini call sites
    # (e.g. "report_card_analysis").
    source = Column(String, nullable=False, index=True)

    submission_id = Column(String, nullable=True, index=True)
    page_id = Column(String, nullable=True, index=True)
    student_id = Column(String, nullable=True, index=True)

    model = Column(String, nullable=False)

    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    thoughts_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)

    # Computed from app/usage_pricing.py at write time. NULL if the model
    # wasn't in the pricing table at the time (rather than silently showing
    # a wrong $0.00 — see usage_pricing.estimate_cost_usd).
    cost_usd = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
