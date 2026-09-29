"""Сквозной интеграционный сценарий жизненного цикла приложения.

Проверяет:
1. Первый запуск: чистая база -> миграции -> сиды -> /health 200 available.
2. Сбой подготовки схемы: повреждение схемы/ревизии -> отказ готовности 503.
3. Повторный запуск: пользовательские записи удаляются,
   исходные сиды восстанавливаются, приложение объявляет готовность 200.
"""

import os
from collections.abc import Generator

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.core import database
from app.core.config import get_settings
from app.demo_data.reset import reset_demo_database
from app.main import app
from app.models.catalog import Item, Location, Supplier
from app.seeds.data import SEED_ITEMS, SEED_LOCATIONS, SEED_SUPPLIERS
from app.seeds.loader import load_seeds

LIFECYCLE_DB_NAME = "abs_lifecycle_integration_test"


def _reset_database(admin_url: str, db_name: str) -> None:
    """Удаляет и пересоздает чистую целевую БД."""
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()


@pytest.fixture(scope="module")
def lifecycle_db_url() -> Generator[str, None, None]:
    """Создаёт изолированную тестовую базу и гарантирует возврат исходного состояния."""
    test_db_url = os.environ["TEST_DATABASE_URL"]
    url = make_url(test_db_url)
    target_url = url.set(database=LIFECYCLE_DB_NAME).render_as_string(hide_password=False)
    admin_url = url.set(database="postgres").render_as_string(hide_password=False)

    _reset_database(admin_url, LIFECYCLE_DB_NAME)
    try:
        yield target_url
    finally:
        os.environ["DATABASE_URL"] = test_db_url
        get_settings.cache_clear()
        if database._engine is not None:
            database._engine.dispose()
        database._engine = None
        database._session_factory = None

        admin_eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_eng.connect() as conn:
            conn.execute(
                text(
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{LIFECYCLE_DB_NAME}' AND pid <> pg_backend_pid()"
                )
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{LIFECYCLE_DB_NAME}"'))
        admin_eng.dispose()


def test_lifecycle_end_to_end_scenarios(
    lifecycle_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сквозной тест первого запуска, сбоя и сброса данных при повторном старте."""
    monkeypatch.setenv("DATABASE_URL", lifecycle_db_url)
    get_settings.cache_clear()
    database._engine = None
    database._session_factory = None

    target_engine = create_engine(lifecycle_db_url)
    target_factory = sessionmaker(bind=target_engine)
    client = TestClient(app)
    alembic_cfg = Config("alembic.ini")

    try:
        # 1. Первый запуск: чистая база -> 503 -> миграции -> сиды -> 200
        is_ready, status_detail = database.check_database_readiness()
        assert is_ready is False
        assert status_detail == "migration_missing"
        assert client.get("/health").status_code == 503

        # Применяем миграции и сиды
        command.upgrade(alembic_cfg, "head")
        reset_demo_database()
        with target_factory() as session:
            load_seeds(session)
            assert session.query(func.count(Item.id)).scalar() == len(SEED_ITEMS)
            assert session.query(func.count(Location.id)).scalar() == len(SEED_LOCATIONS)
            assert session.query(func.count(Supplier.id)).scalar() == len(SEED_SUPPLIERS)

        # Полная готовность
        is_ready, status_detail = database.check_database_readiness()
        assert is_ready is True
        assert status_detail == "available"
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy", "database": "available"}

        # 2. Сбои подготовки схемы и ревизии
        with target_engine.connect() as conn:
            conn.execute(text("ALTER TABLE items RENAME TO items_temp"))
            conn.commit()

        assert database.check_database_readiness() == (False, "schema_incomplete")
        assert client.get("/health").status_code == 503

        with target_engine.connect() as conn:
            conn.execute(text("ALTER TABLE items_temp RENAME TO items"))
            conn.commit()

        expected_rev = database.get_expected_migration_head()
        with target_engine.connect() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = 'corrupted_rev'"))
            conn.commit()

        assert database.check_database_readiness() == (False, "migration_mismatch")
        assert client.get("/health").status_code == 503

        with target_engine.connect() as conn:
            conn.execute(text(f"UPDATE alembic_version SET version_num = '{expected_rev}'"))
            conn.commit()

        # 3. Пользовательские данные и повторный запуск (down -> up)
        with target_factory() as session:
            session.add_all(
                [
                    Item(
                        sku="USER-PERSIST-01",
                        name="Пользовательский крем",
                        category="Уход",
                        unit="шт",
                    ),
                    Location(code="USER-LOC-01", name="Пользовательский склад"),
                    Supplier(supplier_id="USER-SUP-01", name="Пользовательский поставщик"),
                ]
            )
            session.commit()

        # Повторный entrypoint контейнера
        command.upgrade(alembic_cfg, "head")
        reset_demo_database()
        with target_factory() as session:
            load_seeds(session)
            assert session.query(func.count(Location.id)).scalar() == len(SEED_LOCATIONS)
            assert session.query(func.count(Supplier.id)).scalar() == len(SEED_SUPPLIERS)
            assert session.query(func.count(Item.id)).scalar() == len(SEED_ITEMS)
            saved = session.query(Item).filter(Item.sku == "USER-PERSIST-01").first()
            assert saved is None

        assert database.check_database_readiness() == (True, "available")
        assert client.get("/health").status_code == 200

    finally:
        target_engine.dispose()
        if database._engine is not None:
            database._engine.dispose()
        database._engine = None
        database._session_factory = None
        os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
        get_settings.cache_clear()
