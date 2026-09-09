from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.supabase_client import supabase


security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:

    # ---------------------------a--------------------------
    # Authorization header check
    # -----------------------------------------------------

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
        )

    token = credentials.credentials

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing access token",
        )

    # -----------------------------------------------------
    # Validate token with Supabase
    # -----------------------------------------------------

    try:
        response = supabase.auth.get_user(token)

        print("AUTH DEBUG: get_user() succeeded")
        print("AUTH DEBUG: user =", response.user)

        user = response.user

    except Exception as exc:

        print(
            "AUTH DEBUG ERROR TYPE:",
            type(exc).__name__,
        )

        print(
            "AUTH DEBUG ERROR:",
            repr(exc),
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token",
        )

    # -----------------------------------------------------
    # User check
    # -----------------------------------------------------

    if not user:

        print("AUTH DEBUG: user is None")

        raise HTTPException(
            status_code=401,
            detail="User not found",
        )

    # -----------------------------------------------------
    # User metadata
    # -----------------------------------------------------

    metadata = user.user_metadata or {}

    role = metadata.get("role")

    student_login_id = metadata.get(
        "student_login_id"
    )

    parent_id = metadata.get(
        "parent_id"
    )

    # -----------------------------------------------------
    # Debug
    # -----------------------------------------------------

    print(
        "AUTH DEBUG: role =",
        role,
    )

    print(
        "AUTH DEBUG: student_login_id =",
        student_login_id,
    )

    print(
        "AUTH DEBUG: parent_id =",
        parent_id,
    )

    # -----------------------------------------------------
    # Return authenticated user
    # -----------------------------------------------------

    return {
        "sub": user.id,
        "email": user.email,

        # Parent / Student role
        "role": role,

        # Student-specific identity
        "student_login_id": student_login_id,

        # Parent-specific identity
        "parent_id": parent_id,
    }