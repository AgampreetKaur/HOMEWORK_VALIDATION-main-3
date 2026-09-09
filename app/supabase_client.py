from supabase import create_client, Client

from app.config import settings


# Normal client — used for authenticated user operations
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_PUBLISHABLE_KEY,
)


# Admin client — ONLY for backend/server-side operations
# such as creating student authentication accounts.
supabase_admin: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SECRET_KEY,
)