from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    """Application settings."""
    DATABASE_URL: str = "sqlite:///./homework_grader.db"

    
    UPLOAD_DIR: str = "./uploads"

    
    SUPABASE_URL: str = ""
    SUPABASE_PUBLISHABLE_KEY: str = ""
    SUPABASE_SECRET_KEY: str = ""

    
    OCR_ENGINE: str = "gemini"

    OCR_MAX_RESCAN_ATTEMPTS: int = 3
    OCR_LOW_CONFIDENCE_THRESHOLD: float = 0.55

    
    GEMINI_API_KEY: str = ""

    
    GRADING_MODEL: str = "gemini-2.5-pro"

    
    OCR_GEMINI_MODEL: str = "gemini-2.5-flash"

    
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"


settings = Settings()