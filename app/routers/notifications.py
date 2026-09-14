"""
Notifications.

GET /notifications/my is the one endpoint that actually creates new
notifications, via _generate_due_notifications() below — it checks every
scheduled test belonging to the current user for two things:

  1. Has scheduled_at just passed, with no "test_starting" notification
     sent yet? -> notify both the student and the parent.
  2. For a "printed" test only: has scheduled_at + duration_minutes just
     passed, with no "submit_reminder" sent yet? -> notify both, telling
     them to upload the completed paper via Homework Validation.

GET /tests/my calls this same function too (see routers/tests.py), so a
notification can appear whether the user opens the bell icon or just has
My Tests open — either poll will generate and pick it up.
"""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.auth import get_current_user
from app.directory_db import get_directory_db
from app.directory_models import StudentProfile
from app.feature_models import ScheduledTest
from app.notification_models import Notification
from app.notification_schemas import NotificationOut, NotificationListOut


router = APIRouter(prefix="/notifications", tags=["notifications"])


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.max.replace(tzinfo=timezone.utc)


def _logged_in_student(current_user: dict, directory_db: Session):
    if current_user.get("role") != "student":
        return None
    login_id = current_user.get("student_login_id")
    if not login_id:
        return None
    return (
        directory_db.query(StudentProfile)
        .filter(StudentProfile.student_login_id == login_id)
        .first()
    )


def generate_due_notifications(db: Session, *, student_id: str = None, parent_id: str = None) -> None:
    """
    Scans scheduled tests belonging to the given student and/or parent for
    anything that just became due, and writes the corresponding
    Notification rows. Safe to call on every poll — each condition is
    guarded by its own *_notified flag so nothing is ever sent twice.
    """

    if not student_id and not parent_id:
        return

    now = datetime.now(timezone.utc)

    query = db.query(ScheduledTest)
    if student_id and parent_id:
        query = query.filter(or_(ScheduledTest.student_id == student_id, ScheduledTest.parent_id == parent_id))
    elif student_id:
        query = query.filter(ScheduledTest.student_id == student_id)
    else:
        query = query.filter(ScheduledTest.parent_id == parent_id)

    tests = query.filter(ScheduledTest.status != "completed").all()

    for test in tests:
        scheduled_at = _parse_iso(test.scheduled_at)

        # --- "your test is starting now" ---
        if not test.start_notified and scheduled_at <= now:
            kind_label = "printed test" if test.test_mode == "printed" else "test"
            db.add(Notification(
                student_id=test.student_id,
                type="test_starting",
                title=f"{test.title} is starting now",
                message=f"Your {kind_label} \"{test.title}\" is now available to start.",
                related_test_id=test.id,
            ))
            db.add(Notification(
                parent_id=test.parent_id,
                type="test_starting",
                title=f"{test.title} has started",
                message=f"The {kind_label} you scheduled for your child, \"{test.title}\", has started.",
                related_test_id=test.id,
            ))
            test.start_notified = True

        # --- "time's up, please upload your answers" (printed tests only) ---
        if (
            test.test_mode == "printed"
            and not test.submit_reminder_notified
            and test.duration_minutes
            and scheduled_at <= now
        ):
            from datetime import timedelta
            deadline = scheduled_at + timedelta(minutes=test.duration_minutes)
            if deadline <= now:
                db.add(Notification(
                    student_id=test.student_id,
                    type="submit_reminder",
                    title=f"Time's up for {test.title}",
                    message="Please upload your completed answers in the Homework Validation / Uploads section now.",
                    related_test_id=test.id,
                ))
                db.add(Notification(
                    parent_id=test.parent_id,
                    type="submit_reminder",
                    title=f"Time's up for {test.title}",
                    message="The allotted time is over — remind your child to upload their answers for checking.",
                    related_test_id=test.id,
                ))
                test.submit_reminder_notified = True

    db.commit()


@router.get("/my", response_model=NotificationListOut)
def list_my_notifications(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    student = _logged_in_student(current_user, directory_db)

    if student is not None:
        generate_due_notifications(db, student_id=student.id)
        rows = (
            db.query(Notification)
            .filter(Notification.student_id == student.id)
            .order_by(Notification.created_at.desc())
            .limit(50)
            .all()
        )
    else:
        parent_id = current_user["sub"]
        generate_due_notifications(db, parent_id=parent_id)
        rows = (
            db.query(Notification)
            .filter(Notification.parent_id == parent_id)
            .order_by(Notification.created_at.desc())
            .limit(50)
            .all()
        )

    unread = sum(1 for r in rows if not r.is_read)

    return NotificationListOut(unread_count=unread, notifications=rows)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()

    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    student = _logged_in_student(current_user, directory_db)
    owns_it = (
        (student is not None and notif.student_id == student.id)
        or (student is None and notif.parent_id == current_user["sub"])
    )
    if not owns_it:
        raise HTTPException(status_code=403, detail="Not your notification")

    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


@router.post("/read-all")
def mark_all_read(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    student = _logged_in_student(current_user, directory_db)

    query = db.query(Notification)
    if student is not None:
        query = query.filter(Notification.student_id == student.id)
    else:
        query = query.filter(Notification.parent_id == current_user["sub"])

    query.filter(Notification.is_read == False).update({"is_read": True})
    db.commit()

    return {"success": True}
