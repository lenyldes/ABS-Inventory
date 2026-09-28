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
from app.core.config import get_settings
from app.core.database import get_engine, get_session_factory
from tests.safety import ensure_truncate_safety, validate_test_database_safety

# Фиксируем исходный DATABASE_URL окружения до любых возможных замен тестовыми фикстурами
_INITIAL_DATABASE_URL = os.getenv("DATABASE_URL")

pytest_plugins = ("tests.forecasting_fixtures",)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database() -> None:
    """Гарантирует безопасность окружения тестов и применяет миграции Alembic."""
    app_env = os.getenv("APP_ENV")
    test_db_url = os.getenv("TEST_DATABASE_URL")
    # До замены DATABASE_URL определяем адрес рабочей БД:
    # явный MAIN_DATABASE_URL либо исходный DATABASE_URL (если MAIN_DATABASE_URL не задан)
    main_db_url = os.getenv("MAIN_DATABASE_URL")
    if not main_db_url and _INITIAL_DATABASE_URL:
        main_db_url = _INITIAL_DATABASE_URL

    # Валидация безопасности: защитный отказ до любых действий с БД
    validate_test_database_safety(
        app_env=app_env,
        test_db_url=test_db_url,
        main_db_url=main_db_url,
    )

    # Гарантируем, что движок и миграции используют тестовую БД
    assert test_db_url is not None
    os.environ["DATABASE_URL"] = test_db_url
    get_settings.cache_clear()

    url = make_url(test_db_url)
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
    """Сессия БД с гарантированной защитой от очистки рабочей базы данных."""
    engine = get_engine()

    # Защитный барьер перед TRUNCATE
    main_db_candidate = os.getenv("MAIN_DATABASE_URL")
    if not main_db_candidate and _INITIAL_DATABASE_URL != os.getenv("TEST_DATABASE_URL"):
        main_db_candidate = _INITIAL_DATABASE_URL

    ensure_truncate_safety(
        current_database=engine.url.database,
        app_env=os.getenv("APP_ENV"),
        test_db_url=os.getenv("TEST_DATABASE_URL"),
        prohibited_db_urls=(main_db_candidate,) if main_db_candidate else (),
    )

    # Очистка всех предметных таблиц
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
