from typing import Optional

from pydantic import BaseModel


class ParentProfileCreate(BaseModel):
    name: Optional[str] = None


class StudentCreate(BaseModel):
    name: str
    grade: Optional[str] = None
    school: Optional[str] = None
    class_teacher: Optional[str] = None


class StudentDeleteRequest(BaseModel):
    password: str  # the PARENT's own account password, confirmed before deletion