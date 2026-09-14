"""
Chapter management.

Access model:
  Admin   — full CRUD on all chapters.
  Student — read-only; automatically scoped to their own class_level
            (resolved from StudentProfile.grade via their JWT).
  Parent  — read-only; can request chapters for any class_level
            (used to populate the test-generator chapter selector for a
            chosen child).

Endpoints:
  POST   /chapters                      admin: create
  GET    /chapters                      admin: list all (optional ?class_level=&subject= filters)
  GET    /chapters/my                   student: chapters for their own class
  GET    /chapters/by-class/{level}     parent/any: chapters for a given class
  GET    /chapters/{id}                 any auth: full chapter text
  PUT    /chapters/{id}                 admin: update
  DELETE /chapters/{id}                 admin: soft-delete
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user, require_admin
from app.directory_db import get_directory_db
from app.directory_models import StudentProfile
from app.admin_models import Chapter
from app.admin_schemas import ChapterCreate, ChapterOut, ChapterDetailOut, ChapterListOut


router = APIRouter(prefix="/chapters", tags=["chapters"])


# =========================================================
# HELPERS
# =========================================================

def _student_grade(current_user: dict, directory_db: Session) -> Optional[str]:
    """Return the enrolled grade of the logged-in student, or None."""
    if current_user.get("role") != "student":
        return None
    login_id = current_user.get("student_login_id")
    if not login_id:
        return None
    student = (
        directory_db.query(StudentProfile)
        .filter(StudentProfile.student_login_id == login_id)
        .first()
    )
    return student.grade if student else None


# =========================================================
# CREATE  (admin)
# =========================================================

@router.post("", response_model=ChapterOut)
def create_chapter(
    payload: ChapterCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    chapter = Chapter(
        name=payload.name.strip(),
        subject=payload.subject.strip(),
        class_level=str(payload.class_level).strip(),
        text=payload.text,
        summary=payload.summary or (payload.text[:3000] if payload.text else None),
        original_filename=payload.original_filename,
        uploaded_by=current_user["sub"],
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


# =========================================================
# LIST ALL  (admin)
# =========================================================

@router.get("", response_model=ChapterListOut)
def list_all_chapters(
    class_level: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    query = db.query(Chapter).filter(Chapter.is_active == True)
    if class_level:
        query = query.filter(Chapter.class_level == class_level)
    if subject:
        query = query.filter(Chapter.subject == subject)

    rows = query.order_by(Chapter.class_level, Chapter.subject, Chapter.created_at.desc()).all()
    return ChapterListOut(chapters=rows, total=len(rows))


# =========================================================
# MY CHAPTERS  (student — auto-scoped to their class)
# =========================================================

@router.get("/my", response_model=ChapterListOut)
def list_my_chapters(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    grade = _student_grade(current_user, directory_db)

    if not grade:
        # Parent or admin hitting this endpoint — return empty
        return ChapterListOut(chapters=[], total=0)

    rows = (
        db.query(Chapter)
        .filter(Chapter.class_level == grade, Chapter.is_active == True)
        .order_by(Chapter.subject, Chapter.created_at.desc())
        .all()
    )
    return ChapterListOut(chapters=rows, total=len(rows))


# =========================================================
# BY CLASS  (parent portal test generator, or admin)
# =========================================================

@router.get("/by-class/{class_level}", response_model=ChapterListOut)
def list_chapters_by_class(
    class_level: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Chapter)
        .filter(Chapter.class_level == class_level, Chapter.is_active == True)
        .order_by(Chapter.subject, Chapter.created_at.desc())
        .all()
    )
    return ChapterListOut(chapters=rows, total=len(rows))


# =========================================================
# GET ONE  (any authenticated user — includes full text)
# =========================================================

@router.get("/{chapter_id}", response_model=ChapterDetailOut)
def get_chapter(
    chapter_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    directory_db: Session = Depends(get_directory_db),
):
    chapter = (
        db.query(Chapter)
        .filter(Chapter.id == chapter_id, Chapter.is_active == True)
        .first()
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    # Students may only read chapters for their own class
    if current_user.get("role") == "student":
        grade = _student_grade(current_user, directory_db)
        if grade and chapter.class_level != grade:
            raise HTTPException(status_code=403, detail="This chapter is not for your class")

    return chapter


# =========================================================
# UPDATE  (admin)
# =========================================================

@router.put("/{chapter_id}", response_model=ChapterOut)
def update_chapter(
    chapter_id: str,
    payload: ChapterCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    chapter.name = payload.name.strip()
    chapter.subject = payload.subject.strip()
    chapter.class_level = str(payload.class_level).strip()
    chapter.text = payload.text
    chapter.summary = payload.summary or (payload.text[:3000] if payload.text else None)
    chapter.original_filename = payload.original_filename

    db.commit()
    db.refresh(chapter)
    return chapter


# =========================================================
# DELETE  (admin — soft delete)
# =========================================================

@router.delete("/{chapter_id}")
def delete_chapter(
    chapter_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_admin(current_user)

    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    chapter.is_active = False
    db.commit()
    return {"success": True, "id": chapter_id}
