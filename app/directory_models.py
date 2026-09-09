from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.directory_db import DirectoryBase


class Parent(DirectoryBase):
    __tablename__ = "parents"

    id = Column(String, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    children = relationship(
        "StudentProfile",
        back_populates="parent",
        cascade="all, delete-orphan",
    )


class StudentProfile(DirectoryBase):
    __tablename__ = "student_profiles"

    id = Column(String, primary_key=True)

    student_login_id = Column(
        String,
        nullable=False,
        unique=True,
        index=True,
    )

    parent_id = Column(
        String,
        ForeignKey("parents.id"),
        nullable=False,
        index=True,
    )

    name = Column(String, nullable=False)
    grade = Column(String, nullable=True)
    school = Column(String, nullable=True)
    class_teacher = Column(String, nullable=True)
    db_path = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    parent = relationship(
        "Parent",
        back_populates="children",
    )