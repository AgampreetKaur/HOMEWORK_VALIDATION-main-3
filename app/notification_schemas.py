from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, field_serializer


def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    message: Optional[str] = None
    related_test_id: Optional[str] = None
    is_read: bool
    created_at: Optional[datetime] = None

    @field_serializer("created_at")
    def _ser_dt(self, dt: Optional[datetime], _info):
        return _iso_z(dt)

    class Config:
        from_attributes = True


class NotificationListOut(BaseModel):
    unread_count: int
    notifications: List[NotificationOut]
