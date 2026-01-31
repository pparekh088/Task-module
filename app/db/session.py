from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base


def init_db() -> None:
    settings = get_settings()
    engine = create_engine(settings.sql_database_url, pool_pre_ping=True, future=True)
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    settings = get_settings()
    engine = create_engine(settings.sql_database_url, pool_pre_ping=True, future=True)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    db = session_local()
    try:
        yield db
    finally:
        db.close()
