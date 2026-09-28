"""Модульные тесты расчёта остатков при возвратах, просрочке и отсечении по as_of."""

from datetime import date, datetime
from decimal import Decimal

from app.inventory.calculator import calculate_stock_balance
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)


def _make_batch(
    batch_id: int = 1,
    batch_number: str = "B-01",
    receipt_date: date = date(2026, 9, 1),
    expiry_date: date | None = date(2026, 12, 1),
    unit_price: Decimal = Decimal("100.00"),
    receipt_doc_number: str = "DOC-REC-01",
) -> BatchSnapshot:
    return BatchSnapshot(
        id=batch_id,
        item_id=1,
        location_id=1,
        batch_number=batch_number,
        receipt_date=receipt_date,
        expiry_date=expiry_date,
        unit_price=unit_price,
        receipt_doc_number=receipt_doc_number,
        created_at=datetime(2026, 9, 1, 10, 0),
    )


def test_stock_calculation_return_to_batch() -> None:
    """Проверяет возврат неиспользованного материала в исходную партию."""
    batch = _make_batch(batch_id=1)
    m_rec = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    m_consume = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 2),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("4.000"),
        doc_number="CONS-1",
        allocations=(
            AllocationSnapshot(
                id=10,
                batch_id=1,
                quantity=Decimal("4.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )
    m_return = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 3),
        item_id=1,
        location_id=1,
        type="return",
        quantity=Decimal("1.500"),
        doc_number="RET-1",
        batch_id=1,
        parent_movement_id=2,
        parent_allocation_id=10,
    )

    balance = calculate_stock_balance(
        [batch],
        [m_rec, m_consume, m_return],
        as_of=date(2026, 9, 3),
    )
    # 10 - 4 + 1.5 = 7.500
    assert balance.current_stock == Decimal("7.500")
    assert balance.available_stock == Decimal("7.500")


def test_stock_calculation_expired_stock_separation() -> None:
    """Проверяет разделение на учётный, доступный и просроченный остаток."""
    batch_exp = _make_batch(
        batch_id=1,
        batch_number="B-EXP",
        receipt_date=date(2026, 8, 1),
        expiry_date=date(2026, 9, 15),
    )
    batch_fresh = _make_batch(
        batch_id=2,
        batch_number="B-FRESH",
        receipt_date=date(2026, 9, 1),
        expiry_date=date(2026, 11, 1),
    )

    m1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 8, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("3.000"),
        doc_number="REC-EXP",
        batch_id=1,
    )
    m2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("7.000"),
        doc_number="REC-FRESH",
        batch_id=2,
    )

    # На дату 2026-09-20 партия 1 уже просрочена (expiry_date 2026-09-15 < 2026-09-20)
    balance = calculate_stock_balance(
        [batch_exp, batch_fresh],
        [m1, m2],
        as_of=date(2026, 9, 20),
    )
    assert balance.current_stock == Decimal("10.000")
    assert balance.available_stock == Decimal("7.000")
    assert balance.expired_stock == Decimal("3.000")
    assert balance.nearest_expiry_date == date(2026, 11, 1)


def test_stock_calculation_as_of_cutoff_and_cancelled_status() -> None:
    """Проверяет отсечение будущих движений по as_of и игнорирование отменённых."""
    batch = _make_batch(batch_id=1, receipt_date=date(2026, 9, 1))
    m_rec = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    m_future = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 10),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="REC-FUT",
        batch_id=1,
    )
    m_cancelled = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 2),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("4.000"),
        doc_number="CONS-CANC",
        status="cancelled",
        allocations=(
            AllocationSnapshot(
                batch_id=1,
                quantity=Decimal("4.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )

    # На дату 2026-09-05: m_future ещё не наступило, m_cancelled отменено
    balance = calculate_stock_balance(
        [batch],
        [m_rec, m_future, m_cancelled],
        as_of=date(2026, 9, 5),
    )
    assert balance.current_stock == Decimal("10.000")
    assert balance.available_stock == Decimal("10.000")
