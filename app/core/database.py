"""Подключение к PostgreSQL и управление сессиями SQLAlchemy."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import get_settings

Base = declarative_base()

_engine = None
_session_factory = None


def get_engine():
    """Создаёт или возвращает синглтон SQLAlchemy Engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Возвращает фабрику сессий."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """Генератор сессии БД для внедрения зависимостей в эндпоинты."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> bool:
    """Проверяет доступность базы данных коротким запросом.

    Возвращает True при успешном подключении, иначе False без утечки секретов.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
