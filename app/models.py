import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, ForeignKey, Enum, Boolean, JSON, LargeBinary
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class SubmissionStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    GRADING = "grading"
    GRADED = "graded"
    FAILED = "failed"


class QuestionSource(str, enum.Enum):
    EMBEDDED = "embedded"     # questions are written within the scanned pages
    SEPARATE = "separate"     # questions provided independently (e.g. question paper text)
    BOTH = "both"


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, default=gen_uuid)
    student_id = Column(String, nullable=False, index=True)
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.UPLOADED, nullable=False)
    question_source = Column(Enum(QuestionSource), default=QuestionSource.EMBEDDED, nullable=False)
    subject = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    failure_reason = Column(Text, nullable=True)

    pages = relationship("Page", back_populates="submission", cascade="all, delete-orphan", order_by="Page.page_number")
    questions = relationship("Question", back_populates="submission", cascade="all, delete-orphan")
    grading_results = relationship("GradingResult", back_populates="submission", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"

    id = Column(String, primary_key=True, default=gen_uuid)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    file_path = Column(String, nullable=False)
    # Raw bytes of the uploaded page. Read back by services/storage.py's
    # write_temp_copy() for OCR rescans, and served directly by
    # GET /submissions/pages/{id}/file.
    file_data = Column(LargeBinary, nullable=False)
    mime_type = Column(String, nullable=True)
    original_filename = Column(String, nullable=True)
    ocr_attempt_count = Column(Integer, default=0)
    is_approved = Column(Boolean, default=False)

    submission = relationship("Submission", back_populates="pages")
    extracted_texts = relationship(
        "ExtractedText", back_populates="page", cascade="all, delete-orphan", order_by="ExtractedText.version"
    )

    @property
    def current_text(self):
        current = [t for t in self.extracted_texts if t.is_current]
        return current[0] if current else None


class ExtractedText(Base):
    __tablename__ = "extracted_texts"

    id = Column(String, primary_key=True, default=gen_uuid)
    page_id = Column(String, ForeignKey("pages.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    raw_text = Column(Text, nullable=False)
    confidence_score = Column(Float, nullable=True)
    ocr_engine_used = Column(String, nullable=False)
    is_current = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # per-line/word confidence, bounding boxes etc. kept as raw JSON for future UI highlighting
    meta = Column(JSON, nullable=True)

    page = relationship("Page", back_populates="extracted_texts")


class Question(Base):
    __tablename__ = "questions"

    id = Column(String, primary_key=True, default=gen_uuid)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False, index=True)
    question_number = Column(String, nullable=False)  # string to allow "2b", "3.1" etc.
    question_text = Column(Text, nullable=False)
    max_marks = Column(Float, nullable=False, default=10.0)
    rubric = Column(Text, nullable=True)

    submission = relationship("Submission", back_populates="questions")


class GradingResult(Base):
    __tablename__ = "grading_results"

    id = Column(String, primary_key=True, default=gen_uuid)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False, index=True)
    question_number = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    max_score = Column(Float, nullable=False)
    feedback = Column(Text, nullable=True)
    deductions = Column(JSON, nullable=True)   # list of {"reason": ..., "points_lost": ...}
    flagged_illegible = Column(Boolean, default=False)
    raw_model_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("Submission", back_populates="grading_results")
