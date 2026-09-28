"""Интеграционные тесты списаний, возвратов, корректировок и неделимости штук."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.inventory.exceptions import (
    ExcessReturnError,
    HistoricalSufficiencyError,
    InvalidMovementError,
)
from app.inventory.operations import (
    register_consume,
    register_correction,
    register_receipt,
    register_return,
    register_writeoff,
)
from app.models.catalog import Item, Location
from app.models.inventory import Batch


@pytest.fixture
def catalog_setup(db_session: Session) -> tuple[Item, Item, Location]:
    """Товар в литрах, товар в штуках и объект."""
    item_liters = Item(sku="OIL-ADJ-01", name="Масло массажное", category="Масла", unit="л")
    item_pieces = Item(sku="TOWEL-01", name="Полотенце махровое", category="Текстиль", unit="шт")
    loc = Location(code="LOC-ADJ-01", name="SPA Центр")
    db_session.add_all([item_liters, item_pieces, loc])
    db_session.commit()
    return item_liters, item_pieces, loc


def test_writeoff_with_reason_and_batch_deficit(
    db_session: Session,
    catalog_setup: tuple[Item, Item, Location],
) -> None:
    """Списание требует причину и не может превышать остаток партии."""
    item_l, _, loc = catalog_setup

    register_receipt(
        db_session,
        item=item_l,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="REC-WO-1",
        batch_number="B-WO-1",
        expiry_date=date(2026, 12, 1),
        unit_price=Decimal("200.00"),
    )
    db_session.commit()
    batch = db_session.query(Batch).filter_by(batch_number="B-WO-1").one()

    # Списание без причины запрещено
    with pytest.raises(InvalidMovementError):
        register_writeoff(
            db_session,
            item=item_l,
            location=loc,
            operation_date=date(2026, 9, 2),
            quantity=Decimal("1.000"),
            doc_number="WO-NO-REASON",
            batch_id=batch.id,
            reason="",
        )
    db_session.rollback()

    # Успешное списание 2 литров с причиной
    res_wo = register_writeoff(
        db_session,
        item=item_l,
        location=loc,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("2.000"),
        doc_number="WO-VALID",
        batch_id=batch.id,
        reason="Бой тары",
    )
    db_session.commit()
    assert res_wo.current_stock == Decimal("3.000")

    # Попытка списать больше остатка партии (4 литра при остатке 3)
    # вызывает HistoricalSufficiencyError
    with pytest.raises(HistoricalSufficiencyError):
        register_writeoff(
            db_session,
            item=item_l,
            location=loc,
            operation_date=date(2026, 9, 3),
            quantity=Decimal("4.000"),
            doc_number="WO-EXCESS",
            batch_id=batch.id,
            reason="Истечение срока",
        )
    db_session.rollback()


def test_return_line_limit_and_expired_return(
    db_session: Session,
    catalog_setup: tuple[Item, Item, Location],
) -> None:
    """Возврат ограничен строкой выдачи; возврат просроченного пополняет только учётный остаток."""
    item_l, _, loc = catalog_setup

    register_receipt(
        db_session,
        item=item_l,
        location=loc,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-RET-01",
        batch_number="B-RET-01",
        expiry_date=date(2026, 9, 15),  # Срок годности истёк к 2026-09-20
        unit_price=Decimal("150.00"),
    )
    db_session.commit()

    res_cons = register_consume(
        db_session,
        item=item_l,
        location=loc,
        operation_date=date(2026, 8, 10),
        quantity=Decimal("4.000"),
        doc_number="CONS-RET-01",
    )
    db_session.commit()
    alloc_id = res_cons.allocations[0].id

    # Попытка вернуть 5 литров при выдаче 4 вызывает ExcessReturnError
    with pytest.raises(ExcessReturnError):
        register_return(
            db_session,
            item=item_l,
            location=loc,
            operation_date=date(2026, 8, 15),
            quantity=Decimal("5.000"),
            doc_number="RET-EXCESS",
            parent_movement_id=res_cons.movement.id,
            parent_allocation_id=alloc_id,
        )
    db_session.rollback()

    # Возврат 2 литров после истечения срока годности партии (2026-09-20 > expiry_date 2026-09-15)
    res_ret = register_return(
        db_session,
        item=item_l,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("2.000"),
        doc_number="RET-EXPIRED",
        parent_movement_id=res_cons.movement.id,
        parent_allocation_id=alloc_id,
        reason="Возврат неиспользованного остатка",
    )
    db_session.commit()

    # Учётный остаток увеличился (10 - 4 + 2 = 8),
    # но доступный остаток равен 0, так как партия просрочена
    assert res_ret.current_stock == Decimal("8.000")
    assert res_ret.available_stock == Decimal("0.000")


def test_positive_and_negative_correction(
    db_session: Session,
    catalog_setup: tuple[Item, Item, Location],
) -> None:
    """Корректировка со знаком меняет остаток партии."""
    item_l, _, loc = catalog_setup

    register_receipt(
        db_session,
        item=item_l,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-CORR-01",
        batch_number="B-CORR-01",
        expiry_date=date(2026, 12, 1),
        unit_price=Decimal("100.00"),
    )
    db_session.commit()
    batch = db_session.query(Batch).filter_by(batch_number="B-CORR-01").one()

    # Отрицательная корректировка -2
    res_neg = register_correction(
        db_session,
        item=item_l,
        location=loc,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("-2.000"),
        doc_number="CORR-NEG-01",
        batch_id=batch.id,
        reason="Инвентаризационная недостача",
    )
    db_session.commit()
    assert res_neg.current_stock == Decimal("8.000")

    # Положительная корректировка +1
    res_pos = register_correction(
        db_session,
        item=item_l,
        location=loc,
        operation_date=date(2026, 9, 3),
        quantity=Decimal("1.000"),
        doc_number="CORR-POS-01",
        batch_id=batch.id,
        reason="Инвентаризационный излишек",
    )
    db_session.commit()
    assert res_pos.current_stock == Decimal("9.000")


def test_indivisible_pieces_validation(
    db_session: Session,
    catalog_setup: tuple[Item, Item, Location],
) -> None:
    """Для единицы измерения «шт» дробные количества отклоняются."""
    _, item_p, loc = catalog_setup

    with pytest.raises(InvalidMovementError) as exc_info:
        register_receipt(
            db_session,
            item=item_p,
            location=loc,
            operation_date=date(2026, 9, 1),
            quantity=Decimal("2.500"),
            doc_number="REC-PIECES-BAD",
            batch_number="B-P-1",
            expiry_date=None,
            unit_price=Decimal("500.00"),
        )
    db_session.rollback()
    assert exc_info.value.code == "FRACTIONAL_PIECES"
