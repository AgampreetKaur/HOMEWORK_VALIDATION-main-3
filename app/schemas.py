from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

from app.models import SubmissionStatus, QuestionSource


# ---------- Requests ----------

class QuestionIn(BaseModel):
    question_number: str
    question_text: str
    max_marks: float = 10.0
    rubric: Optional[str] = None


class QuestionsBatchIn(BaseModel):
    questions: List[QuestionIn]


class RescanRequest(BaseModel):
    # Optionally target specific pages only; omit to rescan all unapproved pages
    page_ids: Optional[List[str]] = None
    # Optional hint from the student about what went wrong, used to steer preprocessing/prompting
    student_note: Optional[str] = None


class ApproveRequest(BaseModel):
    # Must approve explicitly per page id, prevents accidental approval of an unseen page
    page_ids: List[str]


# ---------- Responses ----------

class ExtractedTextOut(BaseModel):
    version: int
    raw_text: str
    confidence_score: Optional[float]
    ocr_engine_used: str
    is_current: bool
    low_confidence: bool = False

    class Config:
        from_attributes = True


class PageOut(BaseModel):
    id: str
    page_number: int
    original_filename: Optional[str]
    ocr_attempt_count: int
    is_approved: bool
    current_text: Optional[ExtractedTextOut]
    # Relative path to fetch the actual uploaded image/PDF from — see
    # GET /submissions/pages/{page_id}/file. The frontend prepends its
    # own backend URL to this.
    file_url: Optional[str] = None

    class Config:
        from_attributes = True


class QuestionOut(BaseModel):
    id: str
    question_number: str
    question_text: str
    max_marks: float
    rubric: Optional[str]

    class Config:
        from_attributes = True


class GradingResultOut(BaseModel):
    question_number: str
    score: float
    max_score: float
    feedback: Optional[str]
    deductions: Optional[list]
    flagged_illegible: bool

    class Config:
        from_attributes = True


class SubmissionOut(BaseModel):
    id: str
    student_id: str
    status: SubmissionStatus
    question_source: QuestionSource
    subject: Optional[str]
    created_at: datetime
    # Alias of created_at — the frontend's history table reads this
    # field name specifically.
    submission_date: Optional[datetime] = None
    failure_reason: Optional[str]
    pages: List[PageOut] = []
    questions: List[QuestionOut] = []
    # Populated once grading is done (summed from grading_results);
    # None until then.
    total_score: Optional[float] = None
    total_max_score: Optional[float] = None

    class Config:
        from_attributes = True


class SubmissionResultOut(BaseModel):
    id: str
    status: SubmissionStatus
    total_score: float
    total_max_score: float
    results: List[GradingResultOut]

    class Config:
        from_attributes = True
