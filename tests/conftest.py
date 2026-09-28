"""Общая конфигурация и сессионные фикстуры pytest."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture(scope="session", autouse=True)
def setup_test_database() -> None:
    """Гарантирует существование изолированной тестовой базы данных PostgreSQL."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url or "sqlite" in db_url:
        return

    url = make_url(db_url)
    target_db = url.database
    if not target_db:
        return

    # Подключаемся к служебной БД postgres для проверки и создания целевой тестовой базы
    admin_url = url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target_db},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target_db}"'))
    finally:
        admin_engine.dispose()
