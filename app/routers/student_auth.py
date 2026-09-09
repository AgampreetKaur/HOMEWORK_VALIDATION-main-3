from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.supabase_client import supabase


router = APIRouter(
    prefix="/student-auth",
    tags=["student-auth"],
)


class StudentLoginRequest(BaseModel):
    student_id: str
    password: str


@router.post("/login")
def student_login(payload: StudentLoginRequest):
    """
    Authenticates a student using the Student ID and
    the temporary password generated when the parent
    created the student.
    """

    student_id = payload.student_id.strip()

    if not student_id:
        raise HTTPException(
            status_code=400,
            detail="Student ID is required",
        )

    if not payload.password:
        raise HTTPException(
            status_code=400,
            detail="Password is required",
        )

    # Student Auth accounts are created using this
    # internal email format in directory.py.
    student_email = f"{student_id}@students.internal"

    try:
        response = supabase.auth.sign_in_with_password(
            {
                "email": student_email,
                "password": payload.password,
            }
        )

    except Exception as exc:
        print("STUDENT LOGIN ERROR TYPE:", type(exc).__name__)
        print("STUDENT LOGIN ERROR:", repr(exc))

        raise HTTPException(
            status_code=401,
            detail="Invalid Student ID or password",
        )

    if not response.user or not response.session:
        raise HTTPException(
            status_code=401,
            detail="Invalid Student ID or password",
        )

    return {
        "message": "Student login successful",
        "student": {
            "id": response.user.id,
            "student_login_id": student_id,
            "email": response.user.email,
            "name": response.user.user_metadata.get("name"),
            "grade": response.user.user_metadata.get("grade"),
        },
        "session": {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in,
        },
    }


class StudentRefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
def student_refresh(payload: StudentRefreshRequest):
    """
    Exchanges a student's refresh_token (issued at /student-auth/login)
    for a new access_token/refresh_token pair.

    NOTE: the frontend does not yet call this automatically when a
    request gets a 401. Until utils/api.js's backendFetch() is wired to
    retry through this endpoint, students will still need to log in
    again after their access token expires (~1 hour).
    """

    if not payload.refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token is required")

    try:
        response = supabase.auth.refresh_session(payload.refresh_token)
    except Exception as exc:
        print("STUDENT REFRESH ERROR TYPE:", type(exc).__name__)
        print("STUDENT REFRESH ERROR:", repr(exc))
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please log in again.",
        )

    if not response.session:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please log in again.",
        )

    return {
        "session": {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in,
        },
    }