"""Тесты применения миграций Alembic и соответствия схемы моделям."""

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from alembic import command
from app.models.catalog import Item


def test_migration_upgrades_clean_database_and_is_idempotent(db_session: Session) -> None:
    """Проверяет применение миграции к БД и идемпотентность повторного upgrade."""
    alembic_cfg = Config("alembic.ini")

    # Вставляем проверочную запись
    item = Item(sku="MIG-TEST-01", name="Тестовый товар", category="Тест", unit="шт")
    db_session.add(item)
    db_session.commit()

    # Повторный запуск upgrade head не приводит к ошибке и сохраняет существующие данные
    command.upgrade(alembic_cfg, "head")

    saved_item = db_session.get(Item, item.id)
    assert saved_item is not None
    assert saved_item.sku == "MIG-TEST-01"


def test_schema_matches_models_without_drift() -> None:
    """Проверяет, что нет расхождений между ORM-моделями и миграциями (alembic check)."""
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    assert script.get_current_head() is not None

    # command.check проверяет отсутствие немигрированных изменений между metadata и БД
    command.check(alembic_cfg)


def test_no_create_all_at_application_startup() -> None:
    """Проверяет, что create_all не вызывается автоматически в коде приложения."""
    import inspect

    import app.core.database
    import app.main

    main_source = inspect.getsource(app.main)
    db_source = inspect.getsource(app.core.database)

    assert "create_all" not in main_source
    assert "create_all" not in db_source
