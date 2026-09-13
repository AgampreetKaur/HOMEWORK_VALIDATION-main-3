from typing import Optional

from pydantic import BaseModel


class ParentProfileCreate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    qualification: Optional[str] = None
    profession: Optional[str] = None
    spouse_name: Optional[str] = None
    spouse_details: Optional[str] = None


class StudentCreate(BaseModel):
    name: str
    grade: Optional[str] = None
    school: Optional[str] = None
    class_teacher: Optional[str] = None


class StudentDeleteRequest(BaseModel):
    password: str  # the PARENT's own account password, confirmed before deletion