from datetime import datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, field_serializer


def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


# Sources that call Gemini directly from the BROWSER (Test Paper Generator,
# and the parent portal's chapter-grounded MCQ generator for scheduled
# tests) rather than through this backend. The backend never sees these
# requests happen — it only finds out because the frontend reports them
# after the fact, via POST /usage/log-client. See ClientUsageIn below.
CLIENT_USAGE_SOURCES = ("test_generator_student", "test_generator_parent")


class ClientUsageIn(BaseModel):
    source: Literal["test_generator_student", "test_generator_parent"]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    total_tokens: int = 0
    # Required (and used) only when source == "test_generator_parent" — the
    # StudentProfile.id of the child the test was generated for. Ownership
    # is verified server-side against the caller's own JWT before this is
    # trusted; ignored for "test_generator_student", where the caller's own
    # student profile is resolved from their JWT instead.
    student_id: Optional[str] = None


class TokenUsageLogOut(BaseModel):
    id: str
    source: str
    submission_id: Optional[str] = None
    page_id: Optional[str] = None
    student_id: Optional[str] = None
    model: str
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int
    total_tokens: int
    # Estimated cost for this one request, computed at write time from
    # app/usage_pricing.py. None if the model wasn't in the pricing table
    # when this row was logged.
    cost_usd: Optional[float] = None
    created_at: Optional[datetime] = None

    @field_serializer("created_at")
    def _ser_dt(self, dt: Optional[datetime], _info):
        return _iso_z(dt)

    class Config:
        from_attributes = True


class SourceTotals(BaseModel):
    source: str
    request_count: int
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int
    total_tokens: int
    cost_usd: float


class TokenUsageSummary(BaseModel):
    request_count: int
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int
    total_tokens: int
    cost_usd: float
    by_source: List[SourceTotals]
