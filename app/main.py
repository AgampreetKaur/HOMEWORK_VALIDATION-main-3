import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.directory_db import init_directory_db
from app import directory_models
# Import the new models so their tables are registered on Base and created at
# startup (scheduled tests + report cards).
from app import feature_models  # noqa: F401
from app import usage_models  # noqa: F401
from app.routers import submissions, directory, reports, student_auth, tests, report_cards, usage, generation


logging.basicConfig(level=logging.INFO)


app = FastAPI(
    title="Homework Validation & Grading API",
    description=(
        "Backend for scanning handwritten homework/test answers, letting the "
        "student approve the extracted text, then AI-grading it like a teacher."
    ),
    version="0.1.0",
)


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Routers
# ---------------------------------------------------------

app.include_router(submissions.router)
app.include_router(directory.router)
app.include_router(reports.router)
app.include_router(student_auth.router)
app.include_router(tests.router)
app.include_router(report_cards.router)
app.include_router(usage.router)
app.include_router(generation.router)


# ---------------------------------------------------------
# Startup
# ---------------------------------------------------------

@app.on_event("startup")
def on_startup():

    Base.metadata.create_all(bind=engine)
    init_directory_db()

    # create_all() only creates missing tables, not missing columns on
    # tables that already exist. These patch in columns added after the
    # table was first created; each is a no-op once the column exists.
    from sqlalchemy import text

    with engine.connect() as conn:
        for ddl in (
            "ALTER TABLE report_cards ADD COLUMN overview TEXT",
            "ALTER TABLE report_cards ADD COLUMN overview_generated_at DATETIME",
            "ALTER TABLE token_usage_logs ADD COLUMN thoughts_tokens INTEGER DEFAULT 0",
            "ALTER TABLE token_usage_logs ADD COLUMN cost_usd FLOAT",
        ):
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists — fine


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}