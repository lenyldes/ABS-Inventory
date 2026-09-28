"""Подключение к PostgreSQL, управление сессиями и проверка готовности схемы."""

from collections.abc import Generator
from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import get_settings

Base = declarative_base()

_engine = None
_session_factory = None

REQUIRED_TABLES: frozenset[str] = frozenset(
    {
        "items",
        "locations",
        "suppliers",
        "supplier_conditions",
        "purchase_orders",
        "batches",
        "movements",
        "movement_allocations",
        "amendment_sets",
        "amendment_entries",
        "movement_versions",
        "stock_locks",
    }
)


@lru_cache
def get_expected_migration_head() -> str | None:
    """Возвращает ожидаемый идентификатор head-ревизии миграций Alembic."""
    try:
        alembic_cfg = Config("alembic.ini")
        script_dir = ScriptDirectory.from_config(alembic_cfg)
        return script_dir.get_current_head()
    except Exception:
        return None


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
    """Проверяет базовую доступность подключения к БД коротким запросом."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def check_database_readiness() -> tuple[bool, str]:
    """Проверяет доступность базы данных, актуальность миграций и наличие обязательных таблиц.

    Возвращает кортеж (is_ready, status_detail). При ошибках не раскрывает секреты.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            # 1. Проверка базовой сетевой доступности
            conn.execute(text("SELECT 1"))

            # 2. Проверка ревизии Alembic
            try:
                current_rev = conn.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return False, "migration_missing"

            expected_rev = get_expected_migration_head()
            if not expected_rev:
                return False, "migration_head_unknown"

            if current_rev != expected_rev:
                return False, "migration_mismatch"

            # 3. Проверка наличия всех предметных таблиц
            inspector = inspect(conn)
            existing_tables = set(inspector.get_table_names())
            if not REQUIRED_TABLES.issubset(existing_tables):
                return False, "schema_incomplete"

        return True, "available"
    except Exception:
        return False, "unavailable"
