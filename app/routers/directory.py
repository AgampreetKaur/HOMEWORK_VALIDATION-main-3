import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.directory_db import get_directory_db
from app.directory_models import Parent, StudentProfile
from app.directory_schemas import ParentProfileCreate, StudentCreate
from app.supabase_client import supabase_admin


router = APIRouter(
    prefix="/directory",
    tags=["directory"],
)


# =============================================================
# HELPER — GENERATE SIMPLE STUDENT LOGIN ID
# =============================================================

def _generate_student_login_id(
    name: str,
    db: Session,
) -> str:
    """
    Generates a simple, human-friendly student login ID.

    Example:
        Agam -> AGAM123
        Rahul Sharma -> RAHUL123

    The numeric part is randomly generated.
    If the generated ID already exists, another one is generated.
    """

    # ---------------------------------------------------------
    # Take the first name only
    # ---------------------------------------------------------

    first_name = (
        name.strip().split()[0]
        if name and name.strip()
        else "STUDENT"
    )

    # ---------------------------------------------------------
    # Keep only letters/numbers
    # ---------------------------------------------------------

    base_name = re.sub(
        r"[^A-Za-z0-9]",
        "",
        first_name,
    ).upper()

    # ---------------------------------------------------------
    # Keep ID reasonably short
    # ---------------------------------------------------------

    base_name = base_name[:12]

    if not base_name:
        base_name = "STUDENT"

    # ---------------------------------------------------------
    # Generate unique ID
    # ---------------------------------------------------------

    for _ in range(100):

        random_number = secrets.randbelow(900) + 100

        student_login_id = (
            f"{base_name}{random_number}"
        )

        existing_student = (
            db.query(StudentProfile)
            .filter(
                StudentProfile.student_login_id
                == student_login_id
            )
            .first()
        )

        if not existing_student:
            return student_login_id

    raise HTTPException(
        status_code=500,
        detail="Unable to generate a unique student ID",
    )


# =============================================================
# HELPER — GENERATE TEMPORARY PASSWORD
# =============================================================

def _generate_temporary_password(
    name: str,
) -> str:
    """
    Generates a readable temporary password.

    Example:
        Agam -> Agam@4827

    The number is randomly generated.
    """

    first_name = (
        name.strip().split()[0]
        if name and name.strip()
        else "Student"
    )

    # Keep letters/numbers only.
    clean_name = re.sub(
        r"[^A-Za-z0-9]",
        "",
        first_name,
    )

    if not clean_name:
        clean_name = "Student"

    # Capitalize first letter.
    clean_name = (
        clean_name[0].upper()
        + clean_name[1:]
    )

    random_number = secrets.randbelow(9000) + 1000

    return (
        f"{clean_name}@{random_number}"
    )


# =============================================================
# CREATE PARENT
# =============================================================

@router.post("/parent")
def create_parent_profile(
    payload: ParentProfileCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_directory_db),
):
    """
    Creates a local parent profile for the authenticated
    Supabase user.

    Authentication credentials are handled by Supabase Auth.
    This endpoint only stores the parent's profile information
    in the local directory database.
    """

    user_id = current_user["sub"]
    email = current_user.get("email")

    # ---------------------------------------------------------
    # Check if parent profile already exists
    # ---------------------------------------------------------

    existing_parent = (
        db.query(Parent)
        .filter(
            Parent.id == user_id
        )
        .first()
    )

    if existing_parent:
        raise HTTPException(
            status_code=409,
            detail="Parent profile already exists",
        )

    # ---------------------------------------------------------
    # Create parent profile
    # ---------------------------------------------------------

    parent = Parent(
        id=user_id,
        email=email or "",
        name=payload.name,
        address=payload.address,
        qualification=payload.qualification,
        profession=payload.profession,
        spouse_name=payload.spouse_name,
        spouse_details=payload.spouse_details,
    )

    db.add(parent)
    db.commit()
    db.refresh(parent)

    # ---------------------------------------------------------
    # Return created parent profile
    # ---------------------------------------------------------

    return {
        "message": "Parent profile created successfully",
        "parent": {
            "id": parent.id,
            "email": parent.email,
            "name": parent.name,
            "address": parent.address,
            "qualification": parent.qualification,
            "profession": parent.profession,
            "spouse_name": parent.spouse_name,
            "spouse_details": parent.spouse_details,
        },
    }

# =============================================================
# CREATE STUDENT
# =============================================================

@router.post("/students")
def create_student(
    payload: StudentCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_directory_db),
):
    """
    Creates:

    1. A student Supabase Auth account
    2. A local StudentProfile
    3. A parent -> student relationship

    The internal database ID remains a UUID.

    The student-facing login ID is generated from
    the student's name, for example:

        Agam -> AGAM123
        Rahul -> RAHUL456

    The temporary password is also generated dynamically,
    for example:

        Agam@4827
    """

    parent_id = current_user["sub"]

    # ---------------------------------------------------------
    # Verify parent
    # ---------------------------------------------------------

    parent = (
        db.query(Parent)
        .filter(
            Parent.id == parent_id
        )
        .first()
    )

    if not parent:
        raise HTTPException(
            status_code=404,
            detail="Parent profile not found",
        )

    # ---------------------------------------------------------
    # Generate internal database ID
    #
    # IMPORTANT:
    # Keep this as UUID so existing reports, submissions,
    # and database relationships remain compatible.
    # ---------------------------------------------------------

    student_record_id = str(
        uuid.uuid4()
    )

    # ---------------------------------------------------------
    # Generate simple student login ID
    # ---------------------------------------------------------

    student_login_id = (
        _generate_student_login_id(
            payload.name,
            db,
        )
    )

    # ---------------------------------------------------------
    # Generate temporary password
    # ---------------------------------------------------------

    temporary_password = (
        _generate_temporary_password(
            payload.name
        )
    )

    # ---------------------------------------------------------
    # Synthetic email used internally by Supabase Auth
    # ---------------------------------------------------------

    student_email = (
        f"{student_login_id}@students.internal"
    )

    # ---------------------------------------------------------
    # 1. Create student in Supabase Auth
    # ---------------------------------------------------------

    try:

        auth_response = (
            supabase_admin.auth.admin.create_user(
                {
                    "email": student_email,
                    "password": temporary_password,
                    "email_confirm": True,
                    "user_metadata": {
                        "role": "student",

                        # Student-facing login ID
                        "student_login_id": (
                            student_login_id
                        ),

                        "name": payload.name,

                        "grade": payload.grade,

                        "parent_id": parent_id,
                    },
                }
            )
        )

        auth_user = auth_response.user

    except Exception as exc:

        print(
            "STUDENT AUTH CREATE ERROR:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to create student "
                "authentication account"
            ),
        )

    if not auth_user:

        raise HTTPException(
            status_code=500,
            detail=(
                "Student authentication account "
                "was not created"
            ),
        )

    # ---------------------------------------------------------
    # 2. Create local StudentProfile
    # ---------------------------------------------------------

    try:

        student = StudentProfile(
            id=student_record_id,

            # Student-facing ID
            student_login_id=student_login_id,

            parent_id=parent.id,

            name=payload.name,

            grade=payload.grade,

            db_path=(
                f"./student_dbs/"
                f"{student_record_id}.db"
            ),
        )

        db.add(student)

        db.commit()

        db.refresh(student)

    except Exception as exc:

        db.rollback()

        # -----------------------------------------------------
        # Remove Supabase user if local profile creation fails.
        # -----------------------------------------------------

        try:

            supabase_admin.auth.admin.delete_user(
                auth_user.id
            )

        except Exception as cleanup_exc:

            print(
                "STUDENT AUTH CLEANUP ERROR:",
                repr(cleanup_exc),
            )

        print(
            "STUDENT PROFILE CREATE ERROR:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to create student profile"
            ),
        )

    # ---------------------------------------------------------
    # 3. Return credentials to parent
    # ---------------------------------------------------------

    return {
        "message": "Student created successfully",

        "student": {

            # Internal database ID
            "id": student.id,

            # Human-friendly student login ID
            "student_login_id": (
                student.student_login_id
            ),

            "name": student.name,

            "grade": student.grade,

            "db_path": student.db_path,

            # Login credential
            "login_id": (
                student.student_login_id
            ),

            # Show once to parent
            "temporary_password": (
                temporary_password
            ),
        },
    }


# =============================================================
# RESET STUDENT PASSWORD
# =============================================================

@router.post(
    "/students/{student_id}/reset-password"
)
def reset_student_password(
    student_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_directory_db),
):
    """
    Generates a new temporary password for an existing student.

    Only the parent who owns the student can reset
    that student's password.

    The password is NOT stored in the local database.
    It is updated directly in Supabase Auth and returned
    once to the authenticated parent.
    """

    parent_id = current_user["sub"]

    # ---------------------------------------------------------
    # 1. Verify parent
    # ---------------------------------------------------------

    parent = (
        db.query(Parent)
        .filter(
            Parent.id == parent_id
        )
        .first()
    )

    if not parent:

        raise HTTPException(
            status_code=404,
            detail="Parent profile not found",
        )

    # ---------------------------------------------------------
    # 2. Verify student belongs to this parent
    #
    # Here student_id is the INTERNAL StudentProfile.id
    # because the parent portal uses child.id.
    # ---------------------------------------------------------

    student = (
        db.query(StudentProfile)
        .filter(
            StudentProfile.id == student_id,
            StudentProfile.parent_id == parent_id,
        )
        .first()
    )

    if not student:

        raise HTTPException(
            status_code=403,
            detail=(
                "You do not have access to "
                "this student"
            ),
        )

    # ---------------------------------------------------------
    # 3. Generate new temporary password
    # ---------------------------------------------------------

    new_password = (
        _generate_temporary_password(
            student.name
        )
    )

    # ---------------------------------------------------------
    # Synthetic Supabase Auth email
    # ---------------------------------------------------------

    student_email = (
        f"{student.student_login_id}"
        "@students.internal"
    )

    # ---------------------------------------------------------
    # 4. Find Supabase Auth user
    # ---------------------------------------------------------

    try:

        users_response = (
            supabase_admin.auth.admin.list_users()
        )

        auth_users = getattr(
            users_response,
            "users",
            users_response,
        )

        auth_user = None

        for user in auth_users:

            if (
                getattr(
                    user,
                    "email",
                    None,
                )
                == student_email
            ):

                auth_user = user

                break

    except Exception as exc:

        print(
            "STUDENT AUTH LOOKUP ERROR:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to find student "
                "authentication account"
            ),
        )

    if not auth_user:

        raise HTTPException(
            status_code=404,
            detail=(
                "Student authentication "
                "account not found"
            ),
        )

    # ---------------------------------------------------------
    # 5. Update Supabase password
    # ---------------------------------------------------------

    try:

        supabase_admin.auth.admin.update_user_by_id(
            auth_user.id,
            {
                "password": new_password,
            },
        )

    except Exception as exc:

        print(
            "STUDENT PASSWORD RESET ERROR:",
            repr(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to reset student password"
            ),
        )

    # ---------------------------------------------------------
    # 6. Return new temporary password
    # ---------------------------------------------------------

    return {

        "message": (
            "Student password reset successfully"
        ),

        "student": {

            "id": student.id,

            "student_login_id": (
                student.student_login_id
            ),

            "name": student.name,

            "grade": student.grade,

            "temporary_password": (
                new_password
            ),
        },
    }


# =============================================================
# CURRENT PARENT + CHILDREN
# =============================================================

@router.get("/me")
def get_my_directory(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_directory_db),
):
    """
    Returns the currently authenticated parent and all
    students linked to that parent.

    Passwords are intentionally NOT returned here.
    """

    user_id = current_user["sub"]

    parent = (
        db.query(Parent)
        .filter(
            Parent.id == user_id
        )
        .first()
    )

    if not parent:

        raise HTTPException(
            status_code=404,
            detail="Parent profile not found",
        )

    return {

        "parent": {

            "id": parent.id,

            "email": parent.email,

            "name": parent.name,
        },

        "children": [

            {

                # Internal database ID
                "id": child.id,

                # Student-facing login ID
                "student_login_id": (
                    child.student_login_id
                ),

                "name": child.name,

                "grade": child.grade,

                "db_path": child.db_path,
            }

            for child in parent.children
        ],
    }