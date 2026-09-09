"""
Scheduled tests.

A parent generates an MCQ test for one of their children and schedules a time.
The child sees it in their own account, is notified when the time arrives, takes
it in-app, and it's auto-graded immediately.

Access model mirrors submissions.py:
  * Parent  -> may create/list/delete tests for children linked to them.
  * Student -> may list, take and submit only their OWN tests.
"""

import json
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.directory_db import get_directory_db
from app.directory_models import StudentProfile
from app.feature_models import ScheduledTest
from app.feature_schemas import (
    ScheduledTestCreate,
    ScheduledTestSummary,
    ScheduledTestTake,
    TestQuestionPublic,
    TestSubmitIn,
    TestResultOut,
    TestQuestionResult,
)


router = APIRouter(prefix="/tests", tags=["tests"])


# =========================================================
# ACCESS HELPERS
# =========================================================

def _logged_in_student(current_user: dict, directory_db: Session):
    """Return the StudentProfile for a logged-in student, else None."""

    if current_user.get("role") != "student":
        return None

    login_id = current_user.get("student_login_id")

    if not login_id:
        raise HTTPException(
            status_code=403,
            detail="Student identity is missing",
        )

    student = (
        directory_db.query(StudentProfile)
        .filter(StudentProfile.student_login_id == login_id)
        .first()
    )

    if not student:
        raise HTTPException(
            status_code=403,
            detail="Student profile not found",
        )

    return student


def _parent_child(user_id: str, student_id: str, directory_db: Session):
    """Return the child StudentProfile if it belongs to this parent, else 403."""

    student = (
        directory_db.query(StudentProfile)
        .filter(
            StudentProfile.id == student_id,
            StudentProfile.parent_id == user_id,
        )
        .first()
    )

    if not student:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this student",
        )

    return student


def _verify_test_access(test: ScheduledTest, current_user: dict, directory_db: Session):
    """Parent who owns the child, or the child themself."""

    student = _logged_in_student(current_user, directory_db)

    if student is not None:
        if student.id != test.student_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have access to this test",
            )
        return student

    # Parent
    return _parent_child(current_user["sub"], test.student_id, directory_db)


# =========================================================
# TIME HELPERS
# =========================================================

def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        # Fall back to "far future" so a malformed time never auto-unlocks.
        return datetime.max.replace(tzinfo=timezone.utc)


def _is_available(test: ScheduledTest) -> bool:
    if test.status == "completed":
        return False
    return _parse_iso(test.scheduled_at) <= datetime.now(timezone.utc)


def _summary(test: ScheduledTest) -> ScheduledTestSummary:
    return ScheduledTestSummary(
        id=test.id,
        student_id=test.student_id,
        title=test.title,
        subject=test.subject,
        chapter=test.chapter,
        scheduled_at=test.scheduled_at,
        duration_minutes=test.duration_minutes,
        status=test.status,
        total_questions=test.total_questions,
        score=test.score,
        max_score=test.max_score,
        is_available=_is_available(test),
        created_at=test.created_at,
        completed_at=test.completed_at,
    )


# =========================================================
# CREATE (parent)
# =========================================================

@router.post("", response_model=ScheduledTestSummary)
def create_test(
    payload: ScheduledTestCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    # Only a parent can schedule a test for their child.
    if current_user.get("role") == "student":
        raise HTTPException(
            status_code=403,
            detail="Only a parent can schedule a test.",
        )

    _parent_child(current_user["sub"], payload.student_id, directory_db)

    # Normalise every answer_index into range so grading can't break later.
    clean_questions = []
    for q in payload.questions:
        idx = q.answer_index
        if idx < 0 or idx >= len(q.options):
            idx = 0
        clean_questions.append(
            {
                "question": q.question,
                "options": list(q.options),
                "answer_index": idx,
                "explanation": q.explanation or "",
            }
        )

    test = ScheduledTest(
        student_id=payload.student_id,
        parent_id=current_user["sub"],
        title=payload.title.strip() or "Test",
        subject=payload.subject,
        chapter=payload.chapter,
        questions_json=json.dumps(clean_questions),
        total_questions=len(clean_questions),
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        status="scheduled",
    )

    db.add(test)
    db.commit()
    db.refresh(test)

    return _summary(test)


# =========================================================
# LIST — parent view (one child)
# =========================================================

@router.get("/child/{student_id}", response_model=List[ScheduledTestSummary])
def list_child_tests(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    # Parent must own the child, or a student may read their own (by profile id).
    student = _logged_in_student(current_user, directory_db)
    if student is not None:
        if student.id != student_id:
            raise HTTPException(status_code=403, detail="You do not have access to this student")
    else:
        _parent_child(current_user["sub"], student_id, directory_db)

    tests = (
        db.query(ScheduledTest)
        .filter(ScheduledTest.student_id == student_id)
        .order_by(ScheduledTest.scheduled_at.desc())
        .all()
    )

    return [_summary(t) for t in tests]


# =========================================================
# LIST — student view (their own tests)
# =========================================================

@router.get("/my", response_model=List[ScheduledTestSummary])
def list_my_tests(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    student = _logged_in_student(current_user, directory_db)

    if student is None:
        raise HTTPException(
            status_code=403,
            detail="Only a student can view their own tests.",
        )

    tests = (
        db.query(ScheduledTest)
        .filter(ScheduledTest.student_id == student.id)
        .order_by(ScheduledTest.scheduled_at.desc())
        .all()
    )

    return [_summary(t) for t in tests]


# =========================================================
# TAKE (student) — questions WITHOUT answers
# =========================================================

@router.get("/{test_id}/take", response_model=ScheduledTestTake)
def take_test(
    test_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    test = db.query(ScheduledTest).filter(ScheduledTest.id == test_id).first()

    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    student = _logged_in_student(current_user, directory_db)
    if student is None or student.id != test.student_id:
        raise HTTPException(
            status_code=403,
            detail="Only the student can take this test.",
        )

    if test.status == "completed":
        raise HTTPException(status_code=409, detail="You have already completed this test.")

    if not _is_available(test):
        raise HTTPException(
            status_code=403,
            detail="This test isn't available yet — it unlocks at its scheduled time.",
        )

    questions = json.loads(test.questions_json)

    public = [
        TestQuestionPublic(question=q["question"], options=q["options"])
        for q in questions
    ]

    return ScheduledTestTake(
        id=test.id,
        title=test.title,
        subject=test.subject,
        chapter=test.chapter,
        duration_minutes=test.duration_minutes,
        total_questions=test.total_questions,
        questions=public,
    )


# =========================================================
# SUBMIT (student) — auto-grade
# =========================================================

@router.post("/{test_id}/submit", response_model=TestResultOut)
def submit_test(
    test_id: str,
    payload: TestSubmitIn,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    test = db.query(ScheduledTest).filter(ScheduledTest.id == test_id).first()

    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    student = _logged_in_student(current_user, directory_db)
    if student is None or student.id != test.student_id:
        raise HTTPException(
            status_code=403,
            detail="Only the student can submit this test.",
        )

    if test.status == "completed":
        raise HTTPException(status_code=409, detail="This test has already been submitted.")

    if not _is_available(test):
        raise HTTPException(
            status_code=403,
            detail="This test isn't available yet.",
        )

    questions = json.loads(test.questions_json)
    answers = payload.answers or []

    results: List[TestQuestionResult] = []
    score = 0

    for i, q in enumerate(questions):
        chosen = answers[i] if i < len(answers) else -1
        correct_index = q["answer_index"]
        is_correct = chosen == correct_index

        if is_correct:
            score += 1

        results.append(
            TestQuestionResult(
                question=q["question"],
                options=q["options"],
                your_answer=chosen if chosen is not None and chosen >= 0 else None,
                correct_answer=correct_index,
                is_correct=is_correct,
                explanation=q.get("explanation") or None,
            )
        )

    test.status = "completed"
    test.score = score
    test.max_score = len(questions)
    test.answers_json = json.dumps(answers)
    test.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(test)

    return TestResultOut(
        id=test.id,
        title=test.title,
        status=test.status,
        score=score,
        max_score=len(questions),
        total_questions=len(questions),
        results=results,
    )


# =========================================================
# RESULT (parent or student) — full breakdown of a completed test
# =========================================================

@router.get("/{test_id}/result", response_model=TestResultOut)
def get_test_result(
    test_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    test = db.query(ScheduledTest).filter(ScheduledTest.id == test_id).first()

    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    _verify_test_access(test, current_user, directory_db)

    if test.status != "completed":
        raise HTTPException(status_code=409, detail="This test hasn't been completed yet.")

    questions = json.loads(test.questions_json)
    answers = json.loads(test.answers_json) if test.answers_json else []

    results: List[TestQuestionResult] = []

    for i, q in enumerate(questions):
        chosen = answers[i] if i < len(answers) else -1
        correct_index = q["answer_index"]
        results.append(
            TestQuestionResult(
                question=q["question"],
                options=q["options"],
                your_answer=chosen if chosen is not None and chosen >= 0 else None,
                correct_answer=correct_index,
                is_correct=chosen == correct_index,
                explanation=q.get("explanation") or None,
            )
        )

    return TestResultOut(
        id=test.id,
        title=test.title,
        status=test.status,
        score=test.score or 0,
        max_score=test.max_score or len(questions),
        total_questions=len(questions),
        results=results,
    )


# =========================================================
# DELETE (parent)
# =========================================================

@router.delete("/{test_id}")
def delete_test(
    test_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    test = db.query(ScheduledTest).filter(ScheduledTest.id == test_id).first()

    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    # Only the owning parent may delete.
    if current_user.get("role") == "student":
        raise HTTPException(status_code=403, detail="Only a parent can delete a test.")

    _parent_child(current_user["sub"], test.student_id, directory_db)

    db.delete(test)
    db.commit()

    return {"success": True, "id": test_id}
