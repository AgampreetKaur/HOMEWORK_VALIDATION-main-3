from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


# Separate database only for:
# Parent accounts
# Child profiles
# Parent -> Child relationships
# Student database paths

DirectoryBase = declarative_base()

DIRECTORY_DATABASE_URL = "sqlite:///./directory.db"

directory_engine = create_engine(
    DIRECTORY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

DirectorySessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=directory_engine,
)


def get_directory_db():
    db = DirectorySessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_directory_db():
    DirectoryBase.metadata.create_all(bind=directory_engine)

    # create_all() only creates missing tables, not missing columns on
    # tables that already exist. Patches these two in directly; each
    # ALTER is a no-op once the column already exists.
    from sqlalchemy import text

    with directory_engine.connect() as conn:
        for ddl in (
            "ALTER TABLE student_profiles ADD COLUMN school VARCHAR",
            "ALTER TABLE student_profiles ADD COLUMN class_teacher VARCHAR",
        ):
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists — fine