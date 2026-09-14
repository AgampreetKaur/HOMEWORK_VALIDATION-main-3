"""
Admin account management.

POST /admin/register  — creates a new admin Supabase account by calling the
                        Supabase Auth admin REST endpoint directly (bypasses
                        the supabase-py library's admin client, which requires
                        extra session setup).  Requires admin_secret ==
                        settings.ADMIN_SECRET.

GET  /admin/me        — returns the logged-in admin's profile.
                        Returns 403 if the caller is not an admin.
"""

import requests as http_requests

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user, require_admin
from app.config import settings
from app.admin_schemas import AdminRegisterIn, AdminMeOut


router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/register", response_model=AdminMeOut)
def register_admin(payload: AdminRegisterIn):
    """
    Create a new admin account. Protected by a shared secret so it cannot
    be called by the public — only someone who already knows ADMIN_SECRET.
    """
    if not settings.ADMIN_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Admin registration is disabled: ADMIN_SECRET is not configured.",
        )

    if payload.admin_secret != settings.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret.")

    if not settings.SUPABASE_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="SUPABASE_SECRET_KEY is not set in .env — cannot create admin account.",
        )

    # Call the Supabase Auth admin REST API directly.
    # This is equivalent to what supabase_admin.auth.admin.create_user() does
    # internally, but sends the service role key explicitly so there is no
    # ambiguity about which token is being used.
    url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SECRET_KEY}",
        "apikey": settings.SUPABASE_SECRET_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "email": payload.email,
        "password": payload.password,
        "email_confirm": True,
        "user_metadata": {
            "name": payload.name,
            "full_name": payload.name,
            "role": "admin",
        },
    }

    try:
        resp = http_requests.post(url, json=body, headers=headers, timeout=15)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Supabase: {exc}")

    if not resp.ok:
        data = resp.json() if resp.content else {}
        msg = data.get("message") or data.get("error_description") or data.get("error") or resp.text
        raise HTTPException(status_code=resp.status_code, detail=f"Supabase error: {msg}")

    user = resp.json()
    return AdminMeOut(
        id=user["id"],
        email=user.get("email", payload.email),
        name=payload.name,
        role="admin",
    )


@router.get("/me", response_model=AdminMeOut)
def admin_me(current_user: dict = Depends(get_current_user)):
    """
    Returns the admin's own profile. 403 if caller is not an admin.
    Used by the frontend to verify admin identity after Supabase login.
    """
    require_admin(current_user)

    return AdminMeOut(
        id=current_user["sub"],
        email=current_user.get("email", ""),
        name=current_user.get("name"),
        role="admin",
    )