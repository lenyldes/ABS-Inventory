"""Тесты подключения к PostgreSQL и проверки готовности схемы базы данных."""

from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy import text

from app.core import database


def test_database_connection_live() -> None:
    """Проверка доступности реального подключения к PostgreSQL."""
    is_ready = database.check_database_connection()
    assert is_ready is True


def test_database_readiness_live() -> None:
    """Проверка полной готовности реальной схемы: ревизия Alembic и 12 таблиц."""
    is_ready, status_detail = database.check_database_readiness()
    assert is_ready is True
    assert status_detail == "available"


def test_database_readiness_missing_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка обнаружения неполной схемы при отсутствии обязательных таблиц."""

    class MockInspector:
        def get_table_names(self) -> Sequence[str]:
            # Исключаем обязательную таблицу items
            return [t for t in database.REQUIRED_TABLES if t != "items"]

    monkeypatch.setattr(database, "inspect", lambda _conn: MockInspector())
    is_ready, status_detail = database.check_database_readiness()
    assert is_ready is False
    assert status_detail == "schema_incomplete"


def test_database_readiness_migration_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка обнаружения несовпадения ревизии миграций Alembic."""
    real_engine = database.get_engine()

    class MismatchedRevConnection:
        def __init__(self, raw_conn: Any) -> None:
            self._raw = raw_conn

        def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
            sql = str(statement).strip()
            if "alembic_version" in sql:

                class ScalarResult:
                    def scalar(self) -> str:
                        return "obsolete_revision_12345"

                return ScalarResult()
            return self._raw.execute(statement, *args, **kwargs)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            pass

    class MismatchedEngine:
        def connect(self) -> Any:
            return MismatchedRevConnection(real_engine.connect())

    monkeypatch.setattr(database, "get_engine", lambda: MismatchedEngine())
    is_ready, status_detail = database.check_database_readiness()
    assert is_ready is False
    assert status_detail == "migration_mismatch"


def test_database_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка возврата False и unavailable при нарушении соединения."""

    class BrokenConnection:
        def __enter__(self) -> Any:
            raise ConnectionRefusedError("Database host unreachable")

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
            return False

    class BrokenEngine:
        def connect(self) -> Any:
            return BrokenConnection()

    monkeypatch.setattr(database, "get_engine", lambda: BrokenEngine())
    assert database.check_database_connection() is False
    is_ready, status_detail = database.check_database_readiness()
    assert is_ready is False
    assert status_detail == "unavailable"


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
