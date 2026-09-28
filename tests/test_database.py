"""Тесты подключения к PostgreSQL и проверки доступности базы данных."""

import pytest
from sqlalchemy import text

from app.core import database


def test_database_connection_live() -> None:
    """Проверка доступности реального подключения к PostgreSQL."""
    is_ready = database.check_database_connection()
    assert is_ready is True


def test_database_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка возврата False без исключений при нарушении соединения."""

    class BrokenConnection:
        def __enter__(self):
            raise ConnectionRefusedError("Database host unreachable")

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    class BrokenEngine:
        def connect(self):
            return BrokenConnection()

    monkeypatch.setattr(database, "get_engine", lambda: BrokenEngine())
    assert database.check_database_connection() is False


def test_session_executes_query() -> None:
    """Проверка открытия сессии и выполнения тестового запроса."""
    generator = database.get_db()
    session = next(generator)
    try:
        result = session.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        try:
            next(generator)
        except StopIteration:
            pass
