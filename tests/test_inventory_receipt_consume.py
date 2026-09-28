"""Интеграционные тесты сервисов поступления и расхода на PostgreSQL."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.inventory.exceptions import (
    DocumentDuplicateError,
    InsufficientStockError,
    InvalidMovementError,
)
from app.inventory.operations import (
    register_consume,
    register_receipt,
)
from app.models.catalog import Item, Location
from app.models.inventory import Batch, Movement, MovementAllocation


@pytest.fixture
def catalog_fixture(db_session: Session) -> tuple[Item, Location]:
    """Тестовые товар и объект."""
    item = Item(sku="OIL-RC-01", name="Масло эфирное", category="Масла", unit="л")
    loc = Location(code="LOC-RC-01", name="SPA Центр")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_receipt_creates_batch_and_movement(
    db_session: Session,
    catalog_fixture: tuple[Item, Location],
) -> None:
    """Поступление создаёт партию, движение и пересчитывает остатки."""
    item, loc = catalog_fixture

    res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("10.000"),
        doc_number="DOC-REC-101",
        batch_number="B-101",
        expiry_date=date(2027, 3, 10),
        unit_price=Decimal("450.00"),
    )
    db_session.commit()

    assert res.current_stock == Decimal("10.000")
    assert res.available_stock == Decimal("10.000")

    batch = db_session.query(Batch).filter_by(batch_number="B-101").one()
    assert batch.receipt_doc_number == "DOC-REC-101"
    assert batch.unit_price == Decimal("450.00")

    mv = db_session.get(Movement, res.movement.id)
    assert mv is not None
    assert mv.type == "receipt"
    assert mv.batch_id == batch.id


def test_consume_fefo_allocation_and_db_persistence(
    db_session: Session,
    catalog_fixture: tuple[Item, Location],
) -> None:
    """Расход списывает партии по FEFO и сохраняет строки MovementAllocation."""
    item, loc = catalog_fixture

    # Создаём две партии с разными сроками годности
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("3.000"),
        doc_number="REC-B1",
        batch_number="B1-EARLY",
        expiry_date=date(2026, 10, 1),
        unit_price=Decimal("100.00"),
    )
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="REC-B2",
        batch_number="B2-LATER",
        expiry_date=date(2026, 11, 1),
        unit_price=Decimal("120.00"),
    )
    db_session.commit()

    # Списываем 4 литра: 3 из B1-EARLY, 1 из B2-LATER
    res = register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 5),
        quantity=Decimal("4.000"),
        doc_number="CONS-01",
    )
    db_session.commit()

    assert res.current_stock == Decimal("4.000")
    assert res.available_stock == Decimal("4.000")

    allocs = (
        db_session.query(MovementAllocation)
        .filter_by(movement_id=res.movement.id)
        .order_by(MovementAllocation.id.asc())
        .all()
    )
    assert len(allocs) == 2
    b1 = db_session.query(Batch).filter_by(batch_number="B1-EARLY").one()
    b2 = db_session.query(Batch).filter_by(batch_number="B2-LATER").one()
    assert allocs[0].batch_id == b1.id
    assert allocs[0].quantity == Decimal("3.000")
    assert allocs[1].batch_id == b2.id
    assert allocs[1].quantity == Decimal("1.000")


def test_consume_rollback_on_insufficient_stock(
    db_session: Session,
    catalog_fixture: tuple[Item, Location],
) -> None:
    """При нехватке остатка транзакция расхода откатывается без частичных записей."""
    item, loc = catalog_fixture

    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("2.000"),
        doc_number="REC-1",
        batch_number="B-1",
        expiry_date=date(2026, 10, 1),
        unit_price=Decimal("100.00"),
    )
    db_session.commit()

    with pytest.raises(InsufficientStockError):
        register_consume(
            db_session,
            item=item,
            location=loc,
            operation_date=date(2026, 9, 2),
            quantity=Decimal("5.000"),
            doc_number="CONS-FAIL",
        )
    db_session.rollback()

    # Движение не должно сохраниться в базе
    mv = db_session.query(Movement).filter_by(doc_number="CONS-FAIL").scalar()
    assert mv is None


def test_duplicate_doc_number_raises_error(
    db_session: Session,
    catalog_fixture: tuple[Item, Location],
) -> None:
    """Повторное использование активного номера документа на объекте запрещено."""
    item, loc = catalog_fixture

    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("1.000"),
        doc_number="DOC-DUP-01",
        batch_number="B-1",
        expiry_date=date(2026, 10, 1),
        unit_price=Decimal("100.00"),
    )
    db_session.commit()

    with pytest.raises(DocumentDuplicateError):
        register_receipt(
            db_session,
            item=item,
            location=loc,
            operation_date=date(2026, 9, 2),
            quantity=Decimal("2.000"),
            doc_number="DOC-DUP-01",
            batch_number="B-2",
            expiry_date=date(2026, 11, 1),
            unit_price=Decimal("100.00"),
        )
    db_session.rollback()


def test_future_operation_date_raises_error(
    db_session: Session,
    catalog_fixture: tuple[Item, Location],
) -> None:
    """Операция с будущей датой отклоняется."""
    item, loc = catalog_fixture
    future_date = date(2099, 1, 1)

    with pytest.raises(InvalidMovementError) as exc_info:
        register_receipt(
            db_session,
            item=item,
            location=loc,
            operation_date=future_date,
            quantity=Decimal("1.000"),
            doc_number="DOC-FUT-01",
            batch_number="B-FUT",
            expiry_date=None,
            unit_price=Decimal("100.00"),
        )
    db_session.rollback()
    assert exc_info.value.code == "FUTURE_DATE"
