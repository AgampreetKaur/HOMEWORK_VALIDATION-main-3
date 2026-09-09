import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base


# All individual student databases will live here.
STUDENT_DATA_DIR = "./student_data"

os.makedirs(STUDENT_DATA_DIR, exist_ok=True)


# Cache database engines/session factories.
# This avoids creating a new SQLAlchemy engine every request
# for the same student.
_engines = {}


def _get_student_db_path(student_login_id: str) -> str:
    """
    Returns the SQLite database path for a student.

    Example:
        STU-7A21K
        -> ./student_data/STU-7A21K.db
    """
    return os.path.join(
        STUDENT_DATA_DIR,
        f"{student_login_id}.db",
    )


def get_student_session(student_login_id: str):
    """
    Creates/opens the student's own SQLite database.

    The first time a student is seen, their database file
    and all existing homework tables are created automatically.
    """

    if not student_login_id:
        raise ValueError("student_login_id is required")

    if student_login_id not in _engines:
        db_path = _get_student_db_path(student_login_id)

        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )

        # Creates the existing homework tables inside THIS
        # student's database.
        Base.metadata.create_all(bind=engine)

        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )

        _engines[student_login_id] = SessionLocal

    SessionLocal = _engines[student_login_id]

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()