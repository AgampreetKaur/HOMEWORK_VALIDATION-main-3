from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.directory_db import get_directory_db
from app.directory_models import Parent, StudentProfile
from app.models import Submission, SubmissionStatus


router = APIRouter(
    prefix="/reports",
    tags=["reports"],
)


def _verify_report_access(
    student_id: str,
    current_user: dict,
    directory_db: Session,
):
    """
    Verify that the authenticated user can access
    the requested student's report.

    Parent:
        Can access only children linked to that parent.

    Student:
        Can access only their own report.
    """

    user_id = current_user["sub"]
    role = current_user.get("role")

    # =====================================================
    # STUDENT ACCESS
    # =====================================================

    if role == "student":

        student_login_id = current_user.get("student_login_id")

        if not student_login_id:
            raise HTTPException(
                status_code=403,
                detail="Student identity is missing",
            )

        student = (
            directory_db.query(StudentProfile)
            .filter(
                StudentProfile.student_login_id == student_login_id
            )
            .first()
        )

        if not student:
            raise HTTPException(
                status_code=403,
                detail="Student profile not found",
            )

        # Student can ONLY access their own report.
        if student.student_login_id != student_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have access to this student's report",
            )

        return student

    # =====================================================
    # PARENT ACCESS
    # =====================================================

    # We verify the actual Parent profile instead of relying
    # only on the JWT role metadata.

    parent = (
        directory_db.query(Parent)
        .filter(
            Parent.id == user_id
        )
        .first()
    )

    if parent:

        student = (
            directory_db.query(StudentProfile)
            .filter(
                StudentProfile.id == student_id,
                StudentProfile.parent_id == parent.id,
            )
            .first()
        )

        if not student:
            raise HTTPException(
                status_code=403,
                detail="You do not have access to this student's report",
            )

        return student

    # =====================================================
    # UNKNOWN / UNAUTHORIZED USER
    # =====================================================

    raise HTTPException(
        status_code=403,
        detail="Unauthorized role",
    )


@router.get("/student/{student_id}")
def get_student_report(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    """
    Returns performance report for a student.

    Parent:
        Can access reports of their own children.

    Student:
        Can access only their own report.
    """

    # =====================================================
    # 1. VERIFY ACCESS
    # =====================================================

    student = _verify_report_access(
        student_id,
        current_user,
        directory_db,
    )

    # =====================================================
    # 2. GET GRADED SUBMISSIONS
    # =====================================================

    submissions = (
        db.query(Submission)
        .filter(
            Submission.student_id == student.id,
            Submission.status == SubmissionStatus.GRADED,
        )
        .order_by(
            Submission.created_at.desc()
        )
        .all()
    )

    # =====================================================
    # 3. NO GRADED HOMEWORK
    # =====================================================

    if not submissions:
        return {
            "student": {
                "id": student.id,
                "name": student.name,
                "grade": student.grade,
            },
            "overall_average": 0,
            "total_homeworks": 0,
            "strong_subjects": [],
            "weak_subjects": [],
            "subjects": [],
            "homework_history": [],
        }

    # =====================================================
    # 4. SUBJECT-WISE PERFORMANCE
    # =====================================================

    subject_scores = defaultdict(float)
    subject_max_scores = defaultdict(float)
    subject_homework_count = defaultdict(int)

    homework_history = []

    for submission in submissions:

        total_score = sum(
            result.score
            for result in submission.grading_results
        )

        total_max_score = sum(
            result.max_score
            for result in submission.grading_results
        )

        percentage = (
            (total_score / total_max_score) * 100
            if total_max_score > 0
            else 0
        )

        # If subject is missing/empty, use Unknown.
        subject = (
            submission.subject.strip()
            if submission.subject
            and submission.subject.strip()
            else "Unknown"
        )

        subject_scores[subject] += total_score
        subject_max_scores[subject] += total_max_score
        subject_homework_count[subject] += 1

        homework_history.append(
            {
                "submission_id": submission.id,
                "subject": subject,
                "score": total_score,
                "max_score": total_max_score,
                "percentage": round(
                    percentage,
                    2,
                ),
                "status": submission.status.value,
                "created_at": submission.created_at,
            }
        )

    # =====================================================
    # 5. BUILD SUBJECT REPORT
    # =====================================================

    subjects = []

    for subject in subject_scores:

        score = subject_scores[subject]
        max_score = subject_max_scores[subject]

        percentage = (
            (score / max_score) * 100
            if max_score > 0
            else 0
        )

        if percentage >= 75:
            performance = "Strong"
        elif percentage < 50:
            performance = "Weak"
        else:
            performance = "Average"

        subjects.append(
            {
                "subject": subject,
                "average": round(
                    percentage,
                    2,
                ),
                "homework_count": subject_homework_count[
                    subject
                ],
                "performance": performance,
            }
        )

    # =====================================================
    # 6. OVERALL PERFORMANCE
    # =====================================================

    total_score = sum(
        subject_scores.values()
    )

    total_max_score = sum(
        subject_max_scores.values()
    )

    overall_average = (
        (total_score / total_max_score) * 100
        if total_max_score > 0
        else 0
    )

    # =====================================================
    # 7. STRONG / WEAK SUBJECTS
    # =====================================================

    strong_subjects = [
        subject["subject"]
        for subject in subjects
        if subject["performance"] == "Strong"
    ]

    weak_subjects = [
        subject["subject"]
        for subject in subjects
        if subject["performance"] == "Weak"
    ]

    # =====================================================
    # 8. FINAL RESPONSE
    # =====================================================

    return {
        "student": {
            "id": student.id,
            "name": student.name,
            "grade": student.grade,
        },
        "overall_average": round(
            overall_average,
            2,
        ),
        "total_homeworks": len(submissions),
        "strong_subjects": strong_subjects,
        "weak_subjects": weak_subjects,
        "subjects": subjects,
        "homework_history": homework_history,
    }