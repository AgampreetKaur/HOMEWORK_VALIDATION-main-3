from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # Database (SQLite for quick local development)
    DATABASE_URL: str = "sqlite:///./homework_grader.db"

    # File storage
    UPLOAD_DIR: str = "./uploads"

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    SUPABASE_SECRET_KEY: str = ""

    # OCR engine
    # "gemini" = Gemini vision OCR
    # "trocr" = self-hosted handwriting model
    # "tesseract" = printed text OCR
    OCR_ENGINE: str = "gemini"

    OCR_MAX_RESCAN_ATTEMPTS: int = 3
    OCR_LOW_CONFIDENCE_THRESHOLD: float = 0.55

    # Gemini API
    GEMINI_API_KEY: str = ""

    # AI grading model
    GRADING_MODEL: str = "gemini-2.5-pro"

    # Gemini OCR model
    OCR_GEMINI_MODEL: str = "gemini-2.5-flash"

    # Celery / Redis
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Admin registration — POST /admin/register requires this secret.
    # Set to any strong random string in production .env.
    ADMIN_SECRET: str = ""


settings = Settings()