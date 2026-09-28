"""Тесты создания версий и снимков для всех типов складских движений."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.inventory.operations import (
    register_consume,
    register_correction,
    register_receipt,
    register_return,
    register_writeoff,
)
from app.inventory.versions import calculate_changes
from app.models.catalog import Item, Location
from app.models.inventory import Movement


@pytest.fixture
def catalog_setup(db_session: Session) -> tuple[Item, Location]:
    """Базовые товар и объект для тестирования версий движений."""
    item = Item(sku="OIL-HIST-01", name="Масло кедровое", category="Масла", unit="л")
    loc = Location(code="LOC-HIST-01", name="SPA Восток")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_initial_version_created_on_receipt(
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Проверяет создание версии 1 при регистрации прихода."""
    item, loc = catalog_setup

    res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("15.000"),
        doc_number="DOC-REC-HIST-1",
        batch_number="BATCH-H-01",
        expiry_date=date(2027, 3, 20),
        unit_price=Decimal("300.00"),
    )
    db_session.commit()

    mv = db_session.get(Movement, res.movement.id)
    assert mv is not None
    assert len(mv.versions) == 1

    v1 = mv.versions[0]
    assert v1.version_num == 1
    assert v1.action == "create"
    assert v1.reason == "Первичный ввод"
    assert v1.snapshot["quantity"] == "15.000"
    assert v1.snapshot["doc_number"] == "DOC-REC-HIST-1"
    assert v1.snapshot["type"] == "receipt"
    assert v1.snapshot["status"] == "active"
    assert v1.snapshot["allocations"] == []


def test_initial_version_created_on_multi_batch_consume(
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Проверяет создание версии 1 со строками распределения при многопартийном расходе."""
    item, loc = catalog_setup

    # Создаём две партии с разными сроками годности
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("3.000"),
        doc_number="DOC-REC-B1",
        batch_number="BATCH-MB-1",
        expiry_date=date(2026, 11, 1),
        unit_price=Decimal("100.00"),
    )
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("7.000"),
        doc_number="DOC-REC-B2",
        batch_number="BATCH-MB-2",
        expiry_date=date(2026, 12, 1),
        unit_price=Decimal("120.00"),
    )
    db_session.commit()

    # Расход 5 литров по FEFO спишет 3 из B1 и 2 из B2
    res_consume = register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 5),
        quantity=Decimal("5.000"),
        doc_number="DOC-CONS-MULTI",
    )
    db_session.commit()

    mv = db_session.get(Movement, res_consume.movement.id)
    assert mv is not None
    assert len(mv.versions) == 1

    v1 = mv.versions[0]
    assert v1.version_num == 1
    assert v1.action == "create"
    assert v1.snapshot["quantity"] == "5.000"
    assert len(v1.snapshot["allocations"]) == 2

    alloc_quantities = sorted(a["quantity"] for a in v1.snapshot["allocations"])
    assert alloc_quantities == ["2.000", "3.000"]
    for alloc_item in v1.snapshot["allocations"]:
        assert alloc_item["id"] is not None
        assert alloc_item["batch_id"] is not None


def test_initial_version_created_on_writeoff_return_correction(
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Проверяет создание версии 1 для списания, возврата и корректировки."""
    item, loc = catalog_setup

    res_rec = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="DOC-REC-ADJ",
        batch_number="BATCH-ADJ",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("150.00"),
    )
    batch_id = res_rec.movement.batch_id
    assert batch_id is not None

    # Списание
    res_wo = register_writeoff(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("1.000"),
        doc_number="DOC-WO-TEST",
        batch_id=batch_id,
        reason="Истёк срок",
    )
    assert len(res_wo.movement.versions) == 1
    assert res_wo.movement.versions[0].action == "create"

    # Расход и возврат
    res_c = register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 3),
        quantity=Decimal("2.000"),
        doc_number="DOC-C-RET",
    )
    parent_alloc_id = res_c.allocations[0].id
    res_ret = register_return(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 4),
        quantity=Decimal("1.000"),
        doc_number="DOC-RET-TEST",
        parent_movement_id=res_c.movement.id,
        parent_allocation_id=parent_alloc_id,
        reason="Излишек процедуры",
    )
    assert len(res_ret.movement.versions) == 1
    assert res_ret.movement.versions[0].action == "create"

    # Корректировка
    res_corr = register_correction(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 5),
        quantity=Decimal("0.500"),
        doc_number="DOC-CORR-TEST",
        batch_id=batch_id,
        reason="Пересчёт остатка",
    )
    assert len(res_corr.movement.versions) == 1
    assert res_corr.movement.versions[0].action == "create"


def test_calculate_changes_detection() -> None:
    """Проверяет корректность вычисления дельты между снимками версий."""
    snap1 = {
        "id": 1,
        "quantity": "20.000",
        "doc_number": "DOC-101",
        "status": "active",
        "allocations": [],
    }
    snap2 = {
        "id": 1,
        "quantity": "2.000",
        "doc_number": "DOC-101",
        "status": "active",
        "allocations": [],
    }
    changes = calculate_changes(snap1, snap2)
    assert changes == {"quantity": {"old": "20.000", "new": "2.000"}}

    # Без изменений
    assert calculate_changes(snap1, snap1) == {}
    # Первичная версия без предка
    assert calculate_changes(None, snap1) == {}
