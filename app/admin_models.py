"""
Admin + Chapter models.

Admin accounts are ordinary Supabase users whose user_metadata carries
role="admin". The Admin table just stores a display profile; all auth still
goes through Supabase.

Chapter — uploaded by an admin and tagged with class_level (matches
StudentProfile.grade, e.g. "9") and subject. When a student opens the
Chapters page, the backend returns only chapters whose class_level matches
their enrolled grade. When a parent schedules a test the same chapters are
available for the child's grade.
"""

from datetime import datetime

from sqlalchemy import Column, String, Text, Boolean, DateTime

from app.database import Base
from app.models import gen_uuid


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String, primary_key=True, default=gen_uuid)

    name = Column(String, nullable=False)
    subject = Column(String, nullable=False)

    # Matches StudentProfile.grade — "6" | "7" | … | "12"
    class_level = Column(String, nullable=False, index=True)

    # Full text extracted from the PDF by the browser (pdf.js + Tesseract)
    text = Column(Text, nullable=False, default="")

    # Short excerpt for quick previews and the test-generation prompt
    summary = Column(Text, nullable=True)

    original_filename = Column(String, nullable=True)

    # Supabase user-id of the admin who uploaded this
    uploaded_by = Column(String, nullable=False)

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
