"""
Extra database models added on top of the original homework-grader schema.

Two new features live here:

1. ScheduledTest
   A parent generates an MCQ test for one of their children and schedules a
   date/time for it. The child sees it in their own account, gets a
   notification when the scheduled time arrives, takes it in-app, and it is
   auto-graded instantly.

2. ReportCard
   A parent uploads a child's school report card (image/PDF). It is stored on
   disk, analyzed by Gemini into a plain-language overview, and can be
   viewed/downloaded later from the parent's Uploads section. Parent-only —
   the child's own account never sees report cards.

Both models live on the SAME main `Base` as Submission, so they share
homework_grader.db and are created automatically at startup by
`Base.metadata.create_all`. Like Submission, `student_id` here is the
StudentProfile.id from the directory database (NOT the login id), and
`parent_id` is the Parent.id (which equals the parent's Supabase user id).
"""

from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime

from app.database import Base
from app.models import gen_uuid


# =============================================================
# SCHEDULED TEST
# =============================================================

class ScheduledTest(Base):
    __tablename__ = "scheduled_tests"

    id = Column(String, primary_key=True, default=gen_uuid)

    # StudentProfile.id (the child this test is for)
    student_id = Column(String, nullable=False, index=True)

    # Parent.id == parent's Supabase user id (who created it)
    parent_id = Column(String, nullable=False, index=True)

    title = Column(String, nullable=False)
    subject = Column(String, nullable=True)
    chapter = Column(String, nullable=True)

    # JSON list of questions:
    # [{"question": str, "options": [str, str, str, str],
    #   "answer_index": int, "explanation": str}]
    #
    # The correct answer/explanation is ONLY ever sent to the child after they
    # submit — the "take" endpoint strips it out.
    questions_json = Column(Text, nullable=False)

    total_questions = Column(Integer, nullable=False, default=0)

    # Stored as an ISO-8601 UTC string ending in "Z" (the frontend converts the
    # parent's chosen local time to UTC before sending). Keeping it as a string
    # avoids every naive-vs-aware timezone serialization pitfall — the child's
    # "notify me at this time" comparison stays exact.
    scheduled_at = Column(String, nullable=False)

    # Optional in-app time limit once the child starts.
    duration_minutes = Column(Integer, nullable=True)

    # "scheduled" -> "completed"
    status = Column(String, nullable=False, default="scheduled")

    # Filled in after the child submits.
    score = Column(Integer, nullable=True)
    max_score = Column(Integer, nullable=True)
    answers_json = Column(Text, nullable=True)   # list[int] of chosen options

    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


# =============================================================
# REPORT CARD
# =============================================================
# Parent-only feature: a report card and its AI-generated overview are
# visible to the uploading parent alone — never to the child. Every access
# point in routers/report_cards.py checks parent ownership only (no
# "child may view their own" branch, unlike ScheduledTest/Submission).

class ReportCard(Base):
    __tablename__ = "report_cards"

    id = Column(String, primary_key=True, default=gen_uuid)

    # StudentProfile.id (the child this report card belongs to)
    student_id = Column(String, nullable=False, index=True)

    # Parent.id == parent's Supabase user id (who uploaded it)
    parent_id = Column(String, nullable=False, index=True)

    term = Column(String, nullable=True)     # e.g. "Term 1 2025"
    note = Column(Text, nullable=True)

    file_path = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False, default=0)

    # AI-generated overview of the report card's contents (JSON string —
    # see app/services/report_analysis.py). NULL until analysis has run
    # at least once, e.g. if the very first attempt failed.
    overview = Column(Text, nullable=True)
    overview_generated_at = Column(DateTime, nullable=True)

    uploaded_at = Column(DateTime, default=datetime.utcnow)
