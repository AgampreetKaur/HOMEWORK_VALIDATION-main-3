from typing import List, Optional
import mimetypes

from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    Form,
    HTTPException,
    BackgroundTasks,
)
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.directory_db import get_directory_db
from app.directory_models import StudentProfile

from app.models import (
    Submission,
    Page,
    Question,
    SubmissionStatus,
    QuestionSource,
)

from app.schemas import (
    SubmissionOut,
    SubmissionResultOut,
    QuestionsBatchIn,
    RescanRequest,
    ApproveRequest,
)

from app.services.storage import save_upload
from app.services.pipeline import (
    run_ocr_on_submission,
    approve_pages,
    run_grading,
)

from app.config import settings


router = APIRouter(
    prefix="/submissions",
    tags=["submissions"],
)


# =========================================================
# HELPERS
# =========================================================

def _low_conf_flag(text) -> bool:
    return (
        text is not None
        and text.confidence_score is not None
        and text.confidence_score
        < settings.OCR_LOW_CONFIDENCE_THRESHOLD
    )


def _serialize_submission(
    submission: Submission,
) -> SubmissionOut:

    out = SubmissionOut.model_validate(
        submission
    )

    # The frontend's history table reads submission_date/total_score,
    # not created_at — populate both here.
    out.submission_date = submission.created_at

    if submission.grading_results:
        out.total_score = sum(r.score for r in submission.grading_results)
        out.total_max_score = sum(r.max_score for r in submission.grading_results)

    for page_out, page in zip(
        out.pages,
        sorted(
            submission.pages,
            key=lambda p: p.page_number,
        ),
    ):
        if page_out.current_text:
            page_out.current_text.low_confidence = (
                _low_conf_flag(
                    page.current_text
                )
            )
        # validation-app.js's detail view already builds an <img src> from
        # backendUrl + p.file_url — that field just never existed before.
        page_out.file_url = f"/submissions/pages/{page.id}/file"

    return out


# =========================================================
# STUDENT ACCESS CHECK
# =========================================================

def _verify_student_access(
    student_id: str,
    current_user: dict,
    directory_db: Session,
):
    """
    Verify that the authenticated user can access
    the requested student.

    Parent:
        Can access children linked to that parent.

    Student:
        Can access only their own StudentProfile.

    IMPORTANT:
        A student's Supabase Auth UUID is different from
        the StudentProfile.student_login_id.

        The student identity is therefore resolved using
        student_login_id from the authenticated user's
        metadata.
    """

    user_id = current_user["sub"]

    # =====================================================
    # STUDENT ACCESS
    # =====================================================

    if current_user.get("role") == "student":

        student_login_id = current_user.get(
            "student_login_id"
        )

        if not student_login_id:
            raise HTTPException(
                status_code=403,
                detail="Student identity is missing",
            )

        # -------------------------------------------------
        # Find the student's local profile using the
        # Student Login ID.
        # -------------------------------------------------

        student = (
            directory_db.query(
                StudentProfile
            )
            .filter(
                StudentProfile.student_login_id
                == student_login_id
            )
            .first()
        )

        if not student:
            raise HTTPException(
                status_code=403,
                detail="Student profile not found",
            )

        # -------------------------------------------------
        # Make sure the requested student is actually
        # the logged-in student.
        # -------------------------------------------------

        if (
            student.student_login_id
            != student_id
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "You do not have access "
                    "to this student"
                ),
            )

        return student

    # =====================================================
    # PARENT ACCESS
    # =====================================================

    student = (
        directory_db.query(
            StudentProfile
        )
        .filter(
            StudentProfile.id == student_id,
            StudentProfile.parent_id == user_id,
        )
        .first()
    )

    if student:
        return student

    # =====================================================
    # NO ACCESS
    # =====================================================

    raise HTTPException(
        status_code=403,
        detail="You do not have access to this student",
    )


# =========================================================
# SUBMISSION ACCESS CHECK
# =========================================================

def _verify_submission_access(
    submission: Submission,
    current_user: dict,
    directory_db: Session,
):
    """
    Verify that the authenticated user can access
    a particular submission.

    Parent:
        Can access submissions belonging to their children.

    Student:
        Can access only their own submissions.
    """

    user_id = current_user["sub"]

    # =====================================================
    # STUDENT ACCESS
    # =====================================================

    if current_user.get("role") == "student":

        student_login_id = current_user.get(
            "student_login_id"
        )

        if not student_login_id:
            raise HTTPException(
                status_code=403,
                detail="Student identity is missing",
            )

        student = (
            directory_db.query(
                StudentProfile
            )
            .filter(
                StudentProfile.student_login_id
                == student_login_id
            )
            .first()
        )

        if not student:
            raise HTTPException(
                status_code=403,
                detail="Student profile not found",
            )

        if student.id != submission.student_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    "You do not have access "
                    "to this submission"
                ),
            )

        return student

    # =====================================================
    # PARENT ACCESS
    # =====================================================

    student = (
        directory_db.query(
            StudentProfile
        )
        .filter(
            StudentProfile.id
            == submission.student_id,
            StudentProfile.parent_id
            == user_id,
        )
        .first()
    )

    if student:
        return student

    # =====================================================
    # NO ACCESS
    # =====================================================

    raise HTTPException(
        status_code=403,
        detail="You do not have access to this submission",
    )


# =========================================================
# SERVE A PAGE'S UPLOADED FILE (image/PDF)
# =========================================================
# Serves the raw bytes stored in Page.file_data at upload time.

@router.get("/pages/{page_id}/file")
def get_page_file(
    page_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    page = db.query(Page).filter(Page.id == page_id).first()

    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    _verify_submission_access(page.submission, current_user, directory_db)

    if not page.file_data:
        raise HTTPException(status_code=404, detail="No file stored for this page")

    return Response(
        content=page.file_data,
        media_type=page.mime_type or "application/octet-stream",
    )


# =========================================================
# CREATE SUBMISSION
# =========================================================

@router.post(
    "",
    response_model=SubmissionOut,
)
def create_submission(
    background_tasks: BackgroundTasks,
    student_id: str = Form(...),
    subject: Optional[str] = Form(None),
    question_source: QuestionSource = Form(
        QuestionSource.EMBEDDED
    ),
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(
        get_directory_db
    ),
):
    """
    Creates a homework submission.

    Parent:
        Can create a submission for their child.

    Student:
        Can create a submission for themselves.
    """

    # -----------------------------------------------------
    # VERIFY STUDENT ACCESS
    # -----------------------------------------------------

    student = _verify_student_access(
        student_id,
        current_user,
        directory_db,
    )

    # -----------------------------------------------------
    # CREATE SUBMISSION
    # -----------------------------------------------------

    submission = Submission(
        student_id=student.id,
        subject=subject,
        question_source=question_source,
    )

    db.add(submission)
    db.commit()
    db.refresh(submission)

    # -----------------------------------------------------
    # SAVE UPLOADED FILES
    # -----------------------------------------------------

    page_number = 1

    for file in files:

        saved_paths = save_upload(
            submission.id,
            file,
        )

        for path in saved_paths:

            # -------------------------------------------------
            # Read the actual saved file bytes.
            #
            # pages.file_data is NOT NULL in the database,
            # so it must contain the uploaded page bytes.
            # -------------------------------------------------

            try:
                with open(path, "rb") as f:
                    file_data = f.read()

            except OSError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Unable to read saved upload: "
                        f"{path}"
                    ),
                ) from exc

            # -------------------------------------------------
            # Determine MIME type from the actual saved file.
            # -------------------------------------------------

            mime_type, _ = mimetypes.guess_type(path)

            if not mime_type:
                mime_type = "application/octet-stream"

            # PDF pages are converted to PNG by save_upload().
            if path.lower().endswith(".png"):
                mime_type = "image/png"

            elif path.lower().endswith(
                (".jpg", ".jpeg")
            ):
                mime_type = "image/jpeg"

            # -------------------------------------------------
            # Create Page record.
            #
            # IMPORTANT:
            # file_data is now populated.
            # -------------------------------------------------

            db.add(
                Page(
                    submission_id=submission.id,
                    page_number=page_number,
                    file_path=path,
                    file_data=file_data,
                    mime_type=mime_type,
                    original_filename=file.filename,
                )
            )

            page_number += 1

    db.commit()
    db.refresh(submission)

    # -----------------------------------------------------
    # START OCR
    # -----------------------------------------------------

    background_tasks.add_task(
        _run_ocr_job,
        submission.id,
    )

    return _serialize_submission(
        submission
    )


# =========================================================
# GET STUDENT SUBMISSIONS
# =========================================================

@router.get(
    "/student/{student_id}",
    response_model=List[SubmissionOut],
)
def get_student_submissions(
    student_id: str,
    current_user: dict = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(
        get_directory_db
    ),
):
    """
    Returns all homework submissions belonging
    to a student.

    Parent:
        Can view their child's submissions.

    Student:
        Can view only their own submissions.
    """

    # -----------------------------------------------------
    # VERIFY ACCESS
    # -----------------------------------------------------

    student = _verify_student_access(
        student_id,
        current_user,
        directory_db,
    )

    # -----------------------------------------------------
    # GET SUBMISSIONS
    # -----------------------------------------------------

    submissions = (
        db.query(Submission)
        .filter(
            Submission.student_id
            == student.id
        )
        .order_by(
            Submission.created_at.desc()
        )
        .all()
    )

    return [
        _serialize_submission(
            submission
        )
        for submission in submissions
    ]


# =========================================================
# OCR JOB
# =========================================================

def _run_ocr_job(
    submission_id: str,
):
    from app.database import SessionLocal

    db = SessionLocal()

    try:

        submission = (
            db.query(Submission)
            .filter(
                Submission.id
                == submission_id
            )
            .first()
        )

        if submission:

            run_ocr_on_submission(
                db,
                submission,
            )

    finally:

        db.close()


# =========================================================
# GET SINGLE SUBMISSION
# =========================================================

@router.get(
    "/{submission_id}",
    response_model=SubmissionOut,
)
def get_submission(
    submission_id: str,
    current_user: dict = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(
        get_directory_db
    ),
):
    """
    Returns a submission only if the authenticated
    parent or student has access to it.
    """

    submission = (
        db.query(Submission)
        .filter(
            Submission.id == submission_id
        )
        .first()
    )

    if not submission:

        raise HTTPException(
            status_code=404,
            detail="Submission not found",
        )

    _verify_submission_access(
        submission,
        current_user,
        directory_db,
    )

    return _serialize_submission(
        submission
    )


# =========================================================
# ADD QUESTIONS
# =========================================================

@router.post(
    "/{submission_id}/questions",
    response_model=SubmissionOut,
)
def add_questions(
    submission_id: str,
    payload: QuestionsBatchIn,
    current_user: dict = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(
        get_directory_db
    ),
):
    """
    Attach separately-provided questions
    to a submission.

    Parent:
        Can modify their child's submission.

    Student:
        Can modify their own submission.
    """

    submission = (
        db.query(Submission)
        .filter(
            Submission.id == submission_id
        )
        .first()
    )

    if not submission:

        raise HTTPException(
            status_code=404,
            detail="Submission not found",
        )

    _verify_submission_access(
        submission,
        current_user,
        directory_db,
    )

    for q in payload.questions:

        db.add(
            Question(
                submission_id=submission.id,
                question_number=q.question_number,
                question_text=q.question_text,
                max_marks=q.max_marks,
                rubric=q.rubric,
            )
        )

    if (
        submission.question_source
        == QuestionSource.EMBEDDED
    ):
        submission.question_source = (
            QuestionSource.BOTH
        )

    db.commit()
    db.refresh(submission)

    return _serialize_submission(
        submission
    )


# =========================================================
# RESCAN SUBMISSION
# =========================================================

@router.post(
    "/{submission_id}/rescan",
    response_model=SubmissionOut,
)
def rescan_submission(
    submission_id: str,
    payload: RescanRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(
        get_directory_db
    ),
):
    """
    Re-runs OCR on selected pages or all
    unapproved pages.
    """

    submission = (
        db.query(Submission)
        .filter(
            Submission.id == submission_id
        )
        .first()
    )

    if not submission:

        raise HTTPException(
            status_code=404,
            detail="Submission not found",
        )

    _verify_submission_access(
        submission,
        current_user,
        directory_db,
    )

    # -----------------------------------------------------
    # STATUS CHECK
    # -----------------------------------------------------

    if submission.status not in (
        SubmissionStatus.PENDING_APPROVAL,
        SubmissionStatus.EXTRACTING,
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot rescan a submission "
                f"in status "
                f"'{submission.status}'."
            ),
        )

    # -----------------------------------------------------
    # TARGET PAGES
    # -----------------------------------------------------

    target_pages = payload.page_ids or [
        p.id
        for p in submission.pages
        if not p.is_approved
    ]

    # -----------------------------------------------------
    # RESCAN LIMIT
    # -----------------------------------------------------

    maxed_out = [
        p.id
        for p in submission.pages
        if p.id in target_pages
        and p.ocr_attempt_count
        >= settings.OCR_MAX_RESCAN_ATTEMPTS
    ]

    if maxed_out:

        raise HTTPException(
            status_code=409,
            detail=(
                f"Pages {maxed_out} have hit "
                f"the max rescan limit "
                f"({settings.OCR_MAX_RESCAN_ATTEMPTS}). "
                f"Manual review needed instead "
                f"of further rescans."
            ),
        )

    # -----------------------------------------------------
    # START OCR
    # -----------------------------------------------------

    background_tasks.add_task(
        _run_ocr_job_for_pages,
        submission.id,
        target_pages,
        payload.student_note,
    )

    return _serialize_submission(
        submission
    )


# =========================================================
# OCR JOB FOR SELECTED PAGES
# =========================================================

def _run_ocr_job_for_pages(
    submission_id: str,
    page_ids: List[str],
    hint: Optional[str],
):
    from app.database import SessionLocal

    db = SessionLocal()

    try:

        submission = (
            db.query(Submission)
            .filter(
                Submission.id
                == submission_id
            )
            .first()
        )

        if submission:

            run_ocr_on_submission(
                db,
                submission,
                page_ids=page_ids,
                hint=hint,
            )

    finally:

        db.close()


# =========================================================
# APPROVE SUBMISSION
# =========================================================

@router.post(
    "/{submission_id}/approve",
    response_model=SubmissionOut,
)
def approve_submission(
    submission_id: str,
    payload: ApproveRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(
        get_directory_db
    ),
):
    """
    Approves the current extracted text.

    Parent:
        Can approve their child's submission.

    Student:
        Can approve their own submission.
    """

    submission = (
        db.query(Submission)
        .filter(
            Submission.id == submission_id
        )
        .first()
    )

    if not submission:

        raise HTTPException(
            status_code=404,
            detail="Submission not found",
        )

    _verify_submission_access(
        submission,
        current_user,
        directory_db,
    )

    # -----------------------------------------------------
    # QUESTIONS CHECK
    # -----------------------------------------------------

    if not submission.questions:

        raise HTTPException(
            status_code=400,
            detail=(
                "No questions attached to this "
                "submission yet. Either the scan "
                "must contain embedded questions "
                "recognizable at grading time, or "
                "POST questions to "
                "/submissions/{id}/questions "
                "before approving."
            ),
        )

    # -----------------------------------------------------
    # APPROVE PAGES
    # -----------------------------------------------------

    approve_pages(
        db,
        submission,
        payload.page_ids,
    )

    db.refresh(submission)

    # -----------------------------------------------------
    # START GRADING
    # -----------------------------------------------------

    if (
        submission.status
        == SubmissionStatus.APPROVED
    ):

        background_tasks.add_task(
            _run_grading_job,
            submission.id,
        )

    return _serialize_submission(
        submission
    )


# =========================================================
# GRADING JOB
# =========================================================

def _run_grading_job(
    submission_id: str,
):
    from app.database import SessionLocal

    db = SessionLocal()

    try:

        submission = (
            db.query(Submission)
            .filter(
                Submission.id
                == submission_id
            )
            .first()
        )

        if submission:

            run_grading(
                db,
                submission,
            )

    finally:

        db.close()


# =========================================================
# GET RESULT
# =========================================================

@router.get(
    "/{submission_id}/result",
    response_model=SubmissionResultOut,
)
def get_result(
    submission_id: str,
    current_user: dict = Depends(
        get_current_user
    ),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(
        get_directory_db
    ),
):
    """
    Returns grading results only if the submission
    belongs to a student accessible by the
    authenticated parent or student.
    """

    submission = (
        db.query(Submission)
        .filter(
            Submission.id == submission_id
        )
        .first()
    )

    if not submission:

        raise HTTPException(
            status_code=404,
            detail="Submission not found",
        )

    _verify_submission_access(
        submission,
        current_user,
        directory_db,
    )

    # -----------------------------------------------------
    # GRADING STATUS
    # -----------------------------------------------------

    if (
        submission.status
        != SubmissionStatus.GRADED
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                f"Submission not graded yet "
                f"(status={submission.status})."
            ),
        )

    # -----------------------------------------------------
    # CALCULATE SCORE
    # -----------------------------------------------------

    total_score = sum(
        r.score
        for r in submission.grading_results
    )

    total_max = sum(
        r.max_score
        for r in submission.grading_results
    )

    # -----------------------------------------------------
    # RETURN RESULT
    # -----------------------------------------------------

    return SubmissionResultOut(
        id=submission.id,
        status=submission.status,
        total_score=total_score,
        total_max_score=total_max,
        results=submission.grading_results,
    )