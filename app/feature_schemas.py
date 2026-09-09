"""
Pydantic (v2) schemas for the scheduled-test and report-card features.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_serializer


def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a naive-UTC datetime to an ISO-8601 string ending in 'Z'
    so the browser's `new Date(...)` always reads it back as UTC."""
    if dt is None:
        return None
    return dt.isoformat() + "Z"


# =============================================================
# SCHEDULED TESTS
# =============================================================

class TestQuestionIn(BaseModel):
    question: str
    options: List[str] = Field(..., min_length=2, max_length=6)
    answer_index: int
    explanation: Optional[str] = None


class ScheduledTestCreate(BaseModel):
    student_id: str
    title: str
    subject: Optional[str] = None
    chapter: Optional[str] = None
    # ISO-8601 UTC string ending in "Z" (frontend converts local -> UTC).
    scheduled_at: str
    duration_minutes: Optional[int] = None
    questions: List[TestQuestionIn] = Field(..., min_length=1)


class ScheduledTestSummary(BaseModel):
    """List view — no question content, safe for both parent and child."""
    id: str
    student_id: str
    title: str
    subject: Optional[str] = None
    chapter: Optional[str] = None
    scheduled_at: str
    duration_minutes: Optional[int] = None
    status: str
    total_questions: int
    score: Optional[int] = None
    max_score: Optional[int] = None
    is_available: bool = False
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @field_serializer("created_at", "completed_at")
    def _ser_dt(self, dt: Optional[datetime], _info):
        return _iso_z(dt)


class TestQuestionPublic(BaseModel):
    """A question as shown to the child while taking — NO correct answer."""
    question: str
    options: List[str]


class ScheduledTestTake(BaseModel):
    id: str
    title: str
    subject: Optional[str] = None
    chapter: Optional[str] = None
    duration_minutes: Optional[int] = None
    total_questions: int
    questions: List[TestQuestionPublic]


class TestSubmitIn(BaseModel):
    # One chosen option index per question (use -1 for "not answered").
    answers: List[int]


class TestQuestionResult(BaseModel):
    question: str
    options: List[str]
    your_answer: Optional[int] = None
    correct_answer: int
    is_correct: bool
    explanation: Optional[str] = None


class TestResultOut(BaseModel):
    id: str
    title: str
    status: str
    score: int
    max_score: int
    total_questions: int
    results: List[TestQuestionResult]


# =============================================================
# REPORT CARDS
# =============================================================

class ReportCardOut(BaseModel):
    id: str
    student_id: str
    term: Optional[str] = None
    note: Optional[str] = None
    original_filename: str
    mime_type: str
    file_size: int
    overview: Optional[str] = None
    overview_generated_at: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None

    @field_serializer("uploaded_at", "overview_generated_at")
    def _ser_dt(self, dt: Optional[datetime], _info):
        return _iso_z(dt)
