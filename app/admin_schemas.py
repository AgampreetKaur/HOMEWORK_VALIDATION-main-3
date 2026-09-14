from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, field_serializer


def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


# ------------------------------------------------------------------
# Chapter schemas
# ------------------------------------------------------------------

class ChapterCreate(BaseModel):
    name: str
    subject: str
    class_level: str          # "6" … "12"
    text: str                 # full extracted text from PDF
    summary: Optional[str] = None
    original_filename: Optional[str] = None


class ChapterOut(BaseModel):
    """Summary — list responses (no full text to keep payloads small)."""
    id: str
    name: str
    subject: str
    class_level: str
    summary: Optional[str] = None
    original_filename: Optional[str] = None
    uploaded_by: str
    is_active: bool
    created_at: Optional[datetime] = None

    @field_serializer("created_at")
    def _ser_dt(self, dt: Optional[datetime], _info):
        return _iso_z(dt)

    class Config:
        from_attributes = True


class ChapterDetailOut(ChapterOut):
    """Full chapter — single-fetch endpoint (includes text)."""
    text: str


class ChapterListOut(BaseModel):
    chapters: List[ChapterOut]
    total: int


# ------------------------------------------------------------------
# Admin registration
# ------------------------------------------------------------------

class AdminRegisterIn(BaseModel):
    name: str
    email: str
    password: str
    admin_secret: str         # must match ADMIN_SECRET env var


class AdminMeOut(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    role: str
