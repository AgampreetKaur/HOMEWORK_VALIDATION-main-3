"""
Report cards.

A parent uploads a child's school report card (PDF or image). It's stored on
disk, automatically analyzed by Gemini into a parent-friendly overview
(summary, subject-wise marks, attendance, teacher remarks, strengths / areas
to improve — see app/services/report_analysis.py), and listed in the
parent's Uploads section.

PARENT-ONLY FEATURE: unlike ScheduledTest and Submission, there is no
"child may view their own" branch anywhere in this router. A report card
and its overview are visible only to the parent who uploaded it — never to
the child's own account. Every endpoint below checks parent ownership via
_parent_child() and nothing else.
"""

import logging
import os
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    Form,
    HTTPException,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.directory_db import get_directory_db
from app.directory_models import StudentProfile
from app.feature_models import ReportCard
from app.feature_schemas import ReportCardOut
from app.services.report_storage import save_report_card, delete_report_card_file
from app.services.report_analysis import analyze_report_card


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-cards", tags=["report-cards"])


# =========================================================
# ACCESS HELPER — parent only, always
# =========================================================

def _parent_child(user_id: str, student_id: str, directory_db: Session):
    student = (
        directory_db.query(StudentProfile)
        .filter(
            StudentProfile.id == student_id,
            StudentProfile.parent_id == user_id,
        )
        .first()
    )
    if not student:
        raise HTTPException(status_code=403, detail="You do not have access to this student")
    return student


def _require_parent(current_user: dict):
    if current_user.get("role") == "student":
        raise HTTPException(
            status_code=403,
            detail="Report cards are only visible in the parent portal.",
        )


def _run_analysis(record: ReportCard, db: Session) -> None:
    """
    Best-effort: analyze the file and store the overview on the record.
    Failures are logged and swallowed — an upload should never fail just
    because Gemini hiccuped, and the parent can retry via /analyze.
    """
    import json
    from datetime import datetime

    try:
        overview = analyze_report_card(record.file_path, record.mime_type)
        record.overview = json.dumps(overview)
        record.overview_generated_at = datetime.utcnow()
        db.commit()
        db.refresh(record)
    except ValueError as exc:
        logger.warning("Report card analysis failed for %s: %s", record.id, exc)


# =========================================================
# UPLOAD (parent) — also runs the AI overview immediately
# =========================================================

@router.post("", response_model=ReportCardOut)
def upload_report_card(
    student_id: str = Form(...),
    term: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    _require_parent(current_user)
    _parent_child(current_user["sub"], student_id, directory_db)

    try:
        meta = save_report_card(student_id, file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    record = ReportCard(
        student_id=student_id,
        parent_id=current_user["sub"],
        term=(term or None),
        note=(note or None),
        file_path=meta["file_path"],
        original_filename=meta["original_filename"],
        mime_type=meta["mime_type"],
        file_size=meta["file_size"],
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    # Synchronous by design — a single Gemini call, no OCR-then-approve loop
    # needed here (unlike homework submissions), so there's nothing gained
    # by deferring it to a background task. If it fails, `overview` stays
    # NULL and the frontend offers a "Generate overview" retry button.
    _run_analysis(record, db)

    return record


# =========================================================
# RE-ANALYZE (parent) — retry / regenerate the overview
# =========================================================

@router.post("/{card_id}/analyze", response_model=ReportCardOut)
def reanalyze_report_card(
    card_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    _require_parent(current_user)

    card = db.query(ReportCard).filter(ReportCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Report card not found")

    _parent_child(current_user["sub"], card.student_id, directory_db)

    if not os.path.exists(card.file_path):
        raise HTTPException(status_code=404, detail="The stored file is missing on the server.")

    try:
        import json
        from datetime import datetime

        overview = analyze_report_card(card.file_path, card.mime_type)
        card.overview = json.dumps(overview)
        card.overview_generated_at = datetime.utcnow()
        db.commit()
        db.refresh(card)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Could not generate an overview: {exc}")

    return card


# =========================================================
# LIST (parent only)
# =========================================================

@router.get("/child/{student_id}", response_model=List[ReportCardOut])
def list_report_cards(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    _require_parent(current_user)
    _parent_child(current_user["sub"], student_id, directory_db)

    cards = (
        db.query(ReportCard)
        .filter(ReportCard.student_id == student_id)
        .order_by(ReportCard.uploaded_at.desc())
        .all()
    )

    return cards


# =========================================================
# DOWNLOAD / VIEW (parent only)
# =========================================================

@router.get("/{card_id}/file")
def get_report_card_file(
    card_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    _require_parent(current_user)

    card = db.query(ReportCard).filter(ReportCard.id == card_id).first()

    if not card:
        raise HTTPException(status_code=404, detail="Report card not found")

    _parent_child(current_user["sub"], card.student_id, directory_db)

    if not os.path.exists(card.file_path):
        raise HTTPException(status_code=404, detail="The stored file is missing on the server.")

    return FileResponse(
        card.file_path,
        media_type=card.mime_type,
        filename=card.original_filename,
    )


# =========================================================
# DELETE (parent only)
# =========================================================

@router.delete("/{card_id}")
def delete_report_card(
    card_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    _require_parent(current_user)

    card = db.query(ReportCard).filter(ReportCard.id == card_id).first()

    if not card:
        raise HTTPException(status_code=404, detail="Report card not found")

    _parent_child(current_user["sub"], card.student_id, directory_db)

    delete_report_card_file(card.file_path)

    db.delete(card)
    db.commit()

    return {"success": True, "id": card_id}
