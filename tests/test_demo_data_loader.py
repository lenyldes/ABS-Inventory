"""Тесты загрузки и валидации демонстрационного набора данных в БД."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.demo_data.inspection import DemoDataError
from app.demo_data.loader import load_demo_data, prepare_demo_data
from app.demo_data.movements import DEMO_BASE_RECEIPT_DOC
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import (
    Batch,
    Movement,
    MovementAllocation,
)
from app.models.procurement import PurchaseOrder, SupplierCondition

TEST_AS_OF = date(2026, 9, 29)


def test_load_demo_data_on_postgres(db_session: Session) -> None:
    """Проверяет загрузку на пустую PostgreSQL: остатки, FEFO, версии (задача 1.2)."""
    stats = load_demo_data(db_session, as_of=TEST_AS_OF)

    assert stats["locations"] == 2
    assert stats["suppliers"] == 2
    assert stats["items"] == 9
    assert stats["supplier_conditions"] == 8
    assert stats["movements"] == 105
    assert stats["batches"] == 9
    assert stats["orders"] == 1

    # Проверка остатков ключевых SKU
    # 1. Масло DEMO-OIL: приход 140, расход 90, остаток 50
    oil_batch = db_session.query(Batch).filter(Batch.batch_number == "DEMO-BATCH-OIL").one()
    alloc_sum = sum(
        a.quantity
        for a in db_session.query(MovementAllocation)
        .filter(MovementAllocation.batch_id == oil_batch.id)
        .all()
    )
    assert alloc_sum == Decimal("90.000")

    oil_item = db_session.query(Item).filter(Item.sku == "DEMO-OIL").one()
    receipts_total = sum(
        m.quantity
        for m in db_session.query(Movement)
        .filter(Movement.item_id == oil_item.id, Movement.type == "receipt")
        .all()
    )
    consumes_total = sum(
        m.quantity
        for m in db_session.query(Movement)
        .filter(Movement.item_id == oil_item.id, Movement.type == "consume")
        .all()
    )
    assert receipts_total - consumes_total == Decimal("50.000")

    # 2. DEMO-DEFICIT: остаток 5
    def_item = db_session.query(Item).filter(Item.sku == "DEMO-DEFICIT").one()
    def_m = db_session.query(Movement).filter(Movement.item_id == def_item.id).all()
    def_balance = sum(m.quantity if m.type == "receipt" else -m.quantity for m in def_m)
    assert def_balance == Decimal("5.000")

    # 3. FEFO-распределения: для каждого consume движения создано распределение
    consumes = db_session.query(Movement).filter(Movement.type == "consume").all()
    assert len(consumes) == 96
    for c in consumes:
        allocs = (
            db_session.query(MovementAllocation)
            .filter(MovementAllocation.movement_id == c.id)
            .all()
        )
        assert len(allocs) >= 1
        assert sum(a.quantity for a in allocs) == c.quantity

    # 4. Версии движений: для каждого движения создана запись версии через связь versions
    movements = db_session.query(Movement).all()
    assert len(movements) == 105
    for mv in movements:
        assert mv.current_version >= 1
        assert len(mv.versions) >= 1
        assert mv.versions[0].version_num == 1

    # 5. Ожидаемый заказ
    po = (
        db_session.query(PurchaseOrder).filter(PurchaseOrder.doc_number == "DEMO-PO-INCOMING").one()
    )
    assert po.status == "pending"
    assert po.expected_qty == Decimal("20.000")
    assert po.pending_qty == Decimal("20.000")
    assert po.received_qty == Decimal("0.000")


def test_load_demo_data_rollback_on_error(db_session: Session) -> None:
    """Проверяет полный откат транзакции при возникновении сбоя (задача 1.2)."""
    with patch(
        "app.demo_data.loader.register_consume",
        side_effect=RuntimeError("Simulated failure in register_consume"),
    ):
        with pytest.raises(RuntimeError, match="Simulated failure"):
            load_demo_data(db_session, as_of=TEST_AS_OF)

    assert db_session.query(Item).filter(Item.sku.like("DEMO-%")).count() == 0
    assert db_session.query(Location).filter(Location.code.like("DEMO-%")).count() == 0
    assert db_session.query(Supplier).filter(Supplier.supplier_id.like("DEMO-%")).count() == 0
    assert (
        db_session.query(SupplierCondition)
        .join(Item, SupplierCondition.item_id == Item.id)
        .filter(Item.sku.like("DEMO-%"))
        .count()
        == 0
    )
    assert db_session.query(Movement).filter(Movement.doc_number.like("DEMO-%")).count() == 0
    assert db_session.query(Batch).filter(Batch.batch_number.like("DEMO-%")).count() == 0
    assert (
        db_session.query(PurchaseOrder).filter(PurchaseOrder.doc_number.like("DEMO-%")).count() == 0
    )


def test_prepare_demo_data_idempotent_and_different_date(db_session: Session) -> None:
    """Проверяет идемпотентный повтор и отказ при иной as_of без --replace (задача 1.3)."""
    # 1. Первичная подготовка на TEST_AS_OF
    mode1, stats1 = prepare_demo_data(db_session, as_of=TEST_AS_OF)
    assert mode1 == "created"
    assert stats1["movements"] == 105

    # Фиксируем количество строк в таблицах
    counts_before = {
        "items": db_session.query(Item).filter(Item.sku.like("DEMO-%")).count(),
        "locations": db_session.query(Location).filter(Location.code.like("DEMO-%")).count(),
        "suppliers": db_session.query(Supplier).filter(Supplier.supplier_id.like("DEMO-%")).count(),
        "conditions": (
            db_session.query(SupplierCondition)
            .join(Item, SupplierCondition.item_id == Item.id)
            .filter(Item.sku.like("DEMO-%"))
            .count()
        ),
        "movements": db_session.query(Movement).filter(Movement.doc_number.like("DEMO-%")).count(),
        "batches": db_session.query(Batch).filter(Batch.batch_number.like("DEMO-%")).count(),
        "orders": (
            db_session.query(PurchaseOrder).filter(PurchaseOrder.doc_number.like("DEMO-%")).count()
        ),
        "allocations": (
            db_session.query(MovementAllocation)
            .join(Movement, MovementAllocation.movement_id == Movement.id)
            .filter(Movement.doc_number.like("DEMO-%"))
            .count()
        ),
    }

    # 2. Идемпотентный повтор на ту же дату: безопасный no-op
    mode2, stats2 = prepare_demo_data(db_session, as_of=TEST_AS_OF)
    assert mode2 == "idempotent"
    assert stats1 == stats2

    # Количество строк не изменилось
    assert db_session.query(Item).filter(Item.sku.like("DEMO-%")).count() == counts_before["items"]
    assert (
        db_session.query(Movement).filter(Movement.doc_number.like("DEMO-%")).count()
        == counts_before["movements"]
    )
    assert (
        db_session.query(MovementAllocation)
        .join(Movement, MovementAllocation.movement_id == Movement.id)
        .filter(Movement.doc_number.like("DEMO-%"))
        .count()
        == counts_before["allocations"]
    )

    # 3. Отказ при иной as_of без --replace
    other_as_of = date(2026, 9, 15)
    with pytest.raises(DemoDataError, match="--replace"):
        prepare_demo_data(db_session, as_of=other_as_of, replace=False)


def test_prepare_demo_data_missing_and_extra_key(db_session: Session) -> None:
    """Проверяет отказ при отсутствующем или лишнем ключе DEMO- (задача 1.3)."""
    prepare_demo_data(db_session, as_of=TEST_AS_OF)

    # 1. Лишний ключ DEMO-
    extra_loc = Location(code="DEMO-MS-EXTRA", name="Лишний объект")
    db_session.add(extra_loc)
    db_session.commit()

    with pytest.raises(DemoDataError, match="лишние"):
        prepare_demo_data(db_session, as_of=TEST_AS_OF)

    # Удаляем лишний объект
    db_session.delete(extra_loc)
    db_session.commit()

    # 2. Отсутствующий ключ (удаляем одно движение)
    one_movement = (
        db_session.query(Movement).filter(Movement.doc_number == "DEMO-CONS-OIL-90").one()
    )
    db_session.query(MovementAllocation).filter(
        MovementAllocation.movement_id == one_movement.id
    ).delete()
    for v in one_movement.versions:
        db_session.delete(v)
    db_session.delete(one_movement)
    db_session.commit()

    with pytest.raises(DemoDataError, match="отсутствуют"):
        prepare_demo_data(db_session, as_of=TEST_AS_OF)


def test_prepare_demo_data_missing_base_movement(db_session: Session) -> None:
    """Проверяет отказ при отсутствии опорного движения DEMO-REC-OIL-BASE (задача 1.3)."""
    prepare_demo_data(db_session, as_of=TEST_AS_OF)

    # Удаляем опорное движение
    base_m = db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).one()
    for v in base_m.versions:
        db_session.delete(v)
    db_session.delete(base_m)
    db_session.commit()

    with pytest.raises(DemoDataError, match="отсутствует опорное движение"):
        prepare_demo_data(db_session, as_of=TEST_AS_OF)
