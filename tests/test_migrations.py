"""Тесты применения миграций Alembic и соответствия схемы моделям."""

from datetime import date
from decimal import Decimal

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from alembic import command
from app.models.amendments import MovementVersion
from app.models.catalog import Item, Location
from app.models.inventory import Batch, Movement, MovementAllocation


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


def test_backfill_movement_versions_migration_preserves_data(db_session: Session) -> None:
    """Проверяет заполнение версии 1 для движений без аудита и сохранение их строк."""
    # Создаём справочники и движение напрямую в БД (эмулируя состояние до запуска аудита)
    item = Item(sku="MIG-MV-01", name="Тестовое масло", category="Масла", unit="л")
    loc = Location(code="LOC-MIG-01", name="Тестовый склад")
    db_session.add_all([item, loc])
    db_session.flush()

    batch = Batch(
        item_id=item.id,
        location_id=loc.id,
        batch_number="B-MIG-01",
        receipt_date=date(2026, 9, 20),
        unit_price=Decimal("200.00"),
        receipt_doc_number="DOC-MIG-REC",
    )
    db_session.add(batch)
    db_session.flush()

    mv = Movement(
        operation_date=date(2026, 9, 20),
        item_id=item.id,
        location_id=loc.id,
        type="consume",
        quantity=Decimal("5.000"),
        doc_number="DOC-MIG-CONS",
        status="active",
        current_version=1,
    )
    db_session.add(mv)
    db_session.flush()

    alloc = MovementAllocation(
        movement_id=mv.id,
        batch_id=batch.id,
        quantity=Decimal("5.000"),
        unit_price=Decimal("200.00"),
    )
    db_session.add(alloc)
    db_session.commit()

    # Удаляем запись аудита, если она была создана хуком
    db_session.query(MovementVersion).filter_by(movement_id=mv.id).delete()
    db_session.commit()
    assert db_session.query(MovementVersion).filter_by(movement_id=mv.id).count() == 0

    # Запускаем откат до 2df052e2bbd9 и затем upgrade head
    alembic_cfg = Config("alembic.ini")
    command.downgrade(alembic_cfg, "2df052e2bbd9")
    command.upgrade(alembic_cfg, "head")

    # Проверяем, что движение и распределения сохранены без изменений
    saved_mv = db_session.get(Movement, mv.id)
    assert saved_mv is not None
    assert saved_mv.quantity == Decimal("5.000")
    assert saved_mv.doc_number == "DOC-MIG-CONS"
    assert len(saved_mv.allocations) == 1
    assert saved_mv.allocations[0].quantity == Decimal("5.000")
    assert saved_mv.allocations[0].batch_id == batch.id

    # Проверяем, что создана версия 1
    versions = db_session.query(MovementVersion).filter_by(movement_id=mv.id).all()
    assert len(versions) == 1
    v1 = versions[0]
    assert v1.version_num == 1
    assert v1.action == "create"
    assert v1.reason == "Первичный ввод"
    assert v1.snapshot["quantity"] == "5.000"
    assert v1.snapshot["doc_number"] == "DOC-MIG-CONS"
    assert len(v1.snapshot["allocations"]) == 1
    assert v1.snapshot["allocations"][0]["id"] == alloc.id
    assert v1.snapshot["allocations"][0]["quantity"] == "5.000"
    assert v1.snapshot["allocations"][0]["batch_id"] == batch.id
