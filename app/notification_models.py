"""
Notifications.

A single table, shared by both the parent and student side. A row is
created for exactly one recipient — either a student or a parent, never
both — and read back through GET /notifications/my, which resolves the
current logged-in user (whichever kind they are) automatically.

Two ways a notification gets created:

1. Immediately, when a parent schedules a test — see routers/tests.py's
   create_test().
2. Lazily, the next time anyone polls GET /notifications/my or
   GET /tests/my — see _generate_due_notifications() in
   routers/notifications.py. There is no background scheduler/cron in
   this app, so "at the scheduled time" really means "the first poll
   after the scheduled time has passed." Given the frontend polls every
   ~20 seconds, this is close enough to real-time in practice without
   adding new infrastructure.
"""

from datetime import datetime

from sqlalchemy import Column, String, Text, Boolean, DateTime

from app.database import Base
from app.models import gen_uuid


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=gen_uuid)

    # Exactly one of these two is set, never both.
    student_id = Column(String, nullable=True, index=True)
    parent_id = Column(String, nullable=True, index=True)

    # "test_scheduled" | "test_starting" | "submit_reminder"
    type = Column(String, nullable=False)

    title = Column(String, nullable=False)
    message = Column(Text, nullable=True)

    # The ScheduledTest this notification is about, if any.
    related_test_id = Column(String, nullable=True, index=True)

    is_read = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
