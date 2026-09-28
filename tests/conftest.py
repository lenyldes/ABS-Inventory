"""Общая конфигурация и сессионные фикстуры pytest."""

import os
from collections.abc import Generator

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from alembic import command
from app.core.database import get_engine, get_session_factory


@pytest.fixture(scope="session", autouse=True)
def setup_test_database() -> None:
    """Гарантирует существование тестовой БД и применяет к ней миграции Alembic."""
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

    # Применяем миграции Alembic к тестовой БД
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Сессия БД с гарантированной очисткой всех данных между тестами."""
    engine = get_engine()

    # Быстрая очистка всех таблиц в правильном порядке
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text(
                    "TRUNCATE TABLE amendment_entries, amendment_sets, "
                    "movement_versions, movement_allocations, movements, "
                    "stock_locks, batches, purchase_orders, "
                    "supplier_conditions, items, locations, suppliers CASCADE"
                )
            )

    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
