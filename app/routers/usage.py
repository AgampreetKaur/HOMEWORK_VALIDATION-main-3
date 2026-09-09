"""
Live token usage.

Every Gemini call already writes a row to token_usage_logs (see
app/usage_models.py and app/services/pipeline.py). These endpoints just
read that table back — a list for the raw feed, and a summary for
totals/cost monitoring.

NOTE ON ACCESS: there is currently no "admin" role in this app (only
"parent" and "student"), so this is gated to "any authenticated, non-student
user" for now — good enough to keep it out of a student's own account, but
NOT the same as admin-only. Once an admin role exists, swap the check in
_require_non_student() for a proper admin check before relying on this for
anything sensitive (it exposes token volume, which is a reasonable proxy
for your Gemini bill).
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.directory_db import get_directory_db
from app.directory_models import StudentProfile
from app.usage_models import TokenUsageLog
from app.usage_pricing import estimate_cost_usd
from app.usage_schemas import TokenUsageLogOut, TokenUsageSummary, SourceTotals, ClientUsageIn


router = APIRouter(prefix="/usage", tags=["usage"])


def _require_non_student(current_user: dict):
    if current_user.get("role") == "student":
        raise HTTPException(status_code=403, detail="Not available on a student account.")


# =========================================================
# LOG (student or parent) — self-reported client-side Gemini usage
# =========================================================
# The Test Paper Generator (generator-app.js, student) and the parent
# portal's chapter-grounded MCQ generator (utils/api.js's
# mcqAPI.generateFromChapter, used by the Tests tab) both call Gemini
# directly from the browser with the user's own API key — this backend
# never sees those requests happen. This endpoint is how it finds out:
# the frontend calls it right after Gemini responds, forwarding the exact
# usageMetadata Gemini itself returned. Not tamper-proof the way OCR/
# grading logging is (a user could report fabricated numbers), but that's
# an acceptable tradeoff here — nothing costly is gated on this data, it's
# purely for visibility into request volume/cost, same spirit as the rest
# of /usage.

@router.post("/log-client", response_model=TokenUsageLogOut)
def log_client_usage(
    payload: ClientUsageIn,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    role = current_user.get("role")

    if payload.source == "test_generator_student":
        if role != "student":
            raise HTTPException(
                status_code=403,
                detail="Only a student account can report test_generator_student usage.",
            )
        login_id = current_user.get("student_login_id")
        student = (
            directory_db.query(StudentProfile)
            .filter(StudentProfile.student_login_id == login_id)
            .first()
        )
        if not student:
            raise HTTPException(status_code=403, detail="Student profile not found.")
        student_id = student.id

    else:  # "test_generator_parent"
        if role == "student":
            raise HTTPException(
                status_code=403,
                detail="Only a parent account can report test_generator_parent usage.",
            )
        if not payload.student_id:
            raise HTTPException(
                status_code=422,
                detail="student_id is required when reporting usage on behalf of a child.",
            )
        owned_child = (
            directory_db.query(StudentProfile)
            .filter(
                StudentProfile.id == payload.student_id,
                StudentProfile.parent_id == current_user["sub"],
            )
            .first()
        )
        if not owned_child:
            raise HTTPException(status_code=403, detail="You do not have access to this student.")
        student_id = owned_child.id

    log = TokenUsageLog(
        source=payload.source,
        student_id=student_id,
        model=payload.model,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        thoughts_tokens=payload.thoughts_tokens,
        total_tokens=payload.total_tokens,
        cost_usd=estimate_cost_usd(
            payload.model, payload.input_tokens, payload.output_tokens, payload.thoughts_tokens
        ),
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return log


@router.get("/token-logs", response_model=List[TokenUsageLogOut])
def list_token_logs(
    source: Optional[str] = Query(None, description="Filter: 'ocr' or 'grading'"),
    student_id: Optional[str] = Query(None),
    submission_id: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None, description="Only rows created after this ISO timestamp"),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Live feed — most recent requests first. Use this for a "requests
    coming in right now" view (poll it every few seconds from the
    frontend, same pattern as My Tests' notification polling).
    """
    _require_non_student(current_user)

    q = db.query(TokenUsageLog)

    if source:
        q = q.filter(TokenUsageLog.source == source)
    if student_id:
        q = q.filter(TokenUsageLog.student_id == student_id)
    if submission_id:
        q = q.filter(TokenUsageLog.submission_id == submission_id)
    if since:
        q = q.filter(TokenUsageLog.created_at >= since)

    return q.order_by(TokenUsageLog.created_at.desc()).limit(limit).all()


@router.get("/summary", response_model=TokenUsageSummary)
def usage_summary(
    since: Optional[datetime] = Query(None, description="Only include rows created after this ISO timestamp"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Totals — overall, and broken down by source (ocr / grading). Pass
    `since` (e.g. the start of today) to get a rolling window instead of
    all-time totals.
    """
    _require_non_student(current_user)

    base = db.query(TokenUsageLog)
    if since:
        base = base.filter(TokenUsageLog.created_at >= since)

    totals = base.with_entities(
        func.count(TokenUsageLog.id),
        func.coalesce(func.sum(TokenUsageLog.input_tokens), 0),
        func.coalesce(func.sum(TokenUsageLog.output_tokens), 0),
        func.coalesce(func.sum(TokenUsageLog.thoughts_tokens), 0),
        func.coalesce(func.sum(TokenUsageLog.total_tokens), 0),
        func.coalesce(func.sum(TokenUsageLog.cost_usd), 0.0),
    ).first()

    by_source_rows = base.with_entities(
        TokenUsageLog.source,
        func.count(TokenUsageLog.id),
        func.coalesce(func.sum(TokenUsageLog.input_tokens), 0),
        func.coalesce(func.sum(TokenUsageLog.output_tokens), 0),
        func.coalesce(func.sum(TokenUsageLog.thoughts_tokens), 0),
        func.coalesce(func.sum(TokenUsageLog.total_tokens), 0),
        func.coalesce(func.sum(TokenUsageLog.cost_usd), 0.0),
    ).group_by(TokenUsageLog.source).all()

    return TokenUsageSummary(
        request_count=totals[0] or 0,
        input_tokens=totals[1] or 0,
        output_tokens=totals[2] or 0,
        thoughts_tokens=totals[3] or 0,
        total_tokens=totals[4] or 0,
        cost_usd=round(totals[5] or 0.0, 6),
        by_source=[
            SourceTotals(
                source=row[0],
                request_count=row[1],
                input_tokens=row[2],
                output_tokens=row[3],
                thoughts_tokens=row[4],
                total_tokens=row[5],
                cost_usd=round(row[6] or 0.0, 6),
            )
            for row in by_source_rows
        ],
    )
