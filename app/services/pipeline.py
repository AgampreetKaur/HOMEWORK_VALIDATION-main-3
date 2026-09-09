import logging
from typing import Optional, List

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Page, ExtractedText, Submission, SubmissionStatus, GradingResult
from app.usage_models import TokenUsageLog
from app.usage_pricing import estimate_cost_usd
from app.services.ocr.engine_factory import run_ocr
from app.services.grading.grader import grade_submission

logger = logging.getLogger(__name__)


def _log_token_usage(db: Session, *, source: str, model: str, usage: dict,
                      submission_id: Optional[str] = None, page_id: Optional[str] = None,
                      student_id: Optional[str] = None) -> None:
    """
    Writes one row to token_usage_logs. Silently does nothing if there's
    nothing to log (e.g. a non-Gemini OCR engine that reports no token
    usage) — this should never be able to break the actual OCR/grading
    flow it's attached to, so it never raises.
    """
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    thoughts_tokens = usage.get("thoughts_tokens", 0) or 0
    total_tokens = usage.get("total_tokens", 0) or (input_tokens + output_tokens + thoughts_tokens)

    if not (input_tokens or output_tokens or thoughts_tokens or total_tokens):
        return

    try:
        db.add(TokenUsageLog(
            source=source,
            submission_id=submission_id,
            page_id=page_id,
            student_id=student_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
            total_tokens=total_tokens,
            cost_usd=estimate_cost_usd(model, input_tokens, output_tokens, thoughts_tokens),
        ))
        db.commit()
    except Exception:
        logger.exception("Failed to write token usage log (source=%s)", source)
        db.rollback()


def run_ocr_on_page(db: Session, page: Page, hint: Optional[str] = None) -> ExtractedText:
    """
    Runs OCR on a single page, stores the result as a new version, and
    marks any previous version for that page as no longer current.
    Attempt count increments each time this runs (i.e. each rescan).
    """
    page.ocr_attempt_count += 1
    result = run_ocr(page.file_path, attempt=page.ocr_attempt_count, hint=hint)

    # demote previous versions
    for t in page.extracted_texts:
        t.is_current = False

    next_version = (max((t.version for t in page.extracted_texts), default=0)) + 1
    extracted = ExtractedText(
        page_id=page.id,
        version=next_version,
        raw_text=result.text,
        confidence_score=result.confidence,
        ocr_engine_used=result.engine,
        is_current=True,
        meta=result.meta,
    )
    db.add(extracted)
    page.is_approved = False  # any new scan requires fresh approval
    db.commit()
    db.refresh(extracted)

    _log_token_usage(
        db,
        source="ocr",
        model=result.meta.get("model", result.engine),
        usage=result.meta,
        submission_id=page.submission_id,
        page_id=page.id,
        student_id=page.submission.student_id if page.submission else None,
    )

    return extracted


def run_ocr_on_submission(db: Session, submission: Submission, page_ids: Optional[List[str]] = None,
                           hint: Optional[str] = None) -> None:
    submission.status = SubmissionStatus.EXTRACTING
    db.commit()

    pages = submission.pages
    if page_ids:
        pages = [p for p in pages if p.id in page_ids]

    for page in pages:
        if page.ocr_attempt_count >= settings.OCR_MAX_RESCAN_ATTEMPTS:
            logger.warning(
                "Page %s hit max rescan attempts (%s) — leaving last result in place for manual review.",
                page.id, settings.OCR_MAX_RESCAN_ATTEMPTS,
            )
            continue
        run_ocr_on_page(db, page, hint=hint)

    submission.status = SubmissionStatus.PENDING_APPROVAL
    db.commit()


def approve_pages(db: Session, submission: Submission, page_ids: List[str]) -> None:
    pages_by_id = {p.id: p for p in submission.pages}
    for pid in page_ids:
        page = pages_by_id.get(pid)
        if page is None:
            continue
        page.is_approved = True

    db.commit()

    all_approved = all(p.is_approved for p in submission.pages)
    if all_approved:
        submission.status = SubmissionStatus.APPROVED
        db.commit()


def run_grading(db: Session, submission: Submission) -> None:
    """
    Concatenates all approved pages' current text, matches against the
    submission's questions, calls the grading model, and persists results.
    Only call this once submission.status == APPROVED.
    """
    if submission.status != SubmissionStatus.APPROVED:
        raise ValueError(f"Submission {submission.id} is not approved yet (status={submission.status}).")

    submission.status = SubmissionStatus.GRADING
    db.commit()

    try:
        answer_text = "\n\n".join(
            f"--- Page {p.page_number} ---\n{p.current_text.raw_text}"
            for p in submission.pages
            if p.current_text
        )

        questions = [
            {
                "question_number": q.question_number,
                "question_text": q.question_text,
                "max_marks": q.max_marks,
                "rubric": q.rubric,
            }
            for q in submission.questions
        ]

        results = grade_submission(questions, answer_text, subject=submission.subject)

        for r in results:
            db.add(GradingResult(
                submission_id=submission.id,
                question_number=r["question_number"],
                score=r["score"],
                max_score=r["max_score"],
                feedback=r.get("feedback"),
                deductions=r.get("deductions"),
                flagged_illegible=r.get("flagged_illegible", False),
                raw_model_response=r.get("raw_model_response"),
            ))

        submission.status = SubmissionStatus.GRADED
        db.commit()

    except Exception as e:
        logger.exception("Grading failed for submission %s", submission.id)
        submission.status = SubmissionStatus.FAILED
        submission.failure_reason = str(e)
        db.commit()
        raise
