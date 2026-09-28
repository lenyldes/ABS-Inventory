"""Модульные тесты расчёта остатков при поступлениях, расходах, списаниях и корректировках."""

from datetime import date, datetime
from decimal import Decimal

from app.inventory.calculator import (
    calculate_batch_stocks,
    calculate_stock_balance,
)
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


def test_stock_calculation_receipt_and_precision() -> None:
    """Проверяет начальное поступление и сохранение точности Decimal(12,3)."""
    batch = _make_batch(batch_id=1, receipt_date=date(2026, 9, 10))
    receipt = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 10),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("12.345"),
        doc_number="DOC-01",
        batch_id=1,
        status="active",
    )

    balance = calculate_stock_balance([batch], [receipt], as_of=date(2026, 9, 10))
    assert balance.current_stock == Decimal("12.345")
    assert balance.available_stock == Decimal("12.345")
    assert balance.expired_stock == Decimal("0.000")
    assert balance.nearest_expiry_date == date(2026, 12, 1)


def test_stock_calculation_consume_with_allocations() -> None:
    """Проверяет списание расхода по строкам распределений."""
    batch1 = _make_batch(batch_id=1, batch_number="B-1", expiry_date=date(2026, 10, 1))
    batch2 = _make_batch(batch_id=2, batch_number="B-2", expiry_date=date(2026, 11, 1))

    m_rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    m_rec2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 2),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-2",
        batch_id=2,
    )
    m_consume = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 5),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("15.000"),
        doc_number="CONS-1",
        allocations=(
            AllocationSnapshot(
                batch_id=1,
                quantity=Decimal("10.000"),
                unit_price=Decimal("100.00"),
            ),
            AllocationSnapshot(
                batch_id=2,
                quantity=Decimal("5.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )

    balance = calculate_stock_balance(
        [batch1, batch2],
        [m_rec1, m_rec2, m_consume],
        as_of=date(2026, 9, 5),
    )
    assert balance.current_stock == Decimal("5.000")
    assert balance.available_stock == Decimal("5.000")
    assert balance.expired_stock == Decimal("0.000")
    assert balance.nearest_expiry_date == date(2026, 11, 1)

    batch_stocks = calculate_batch_stocks(
        [batch1, batch2],
        [m_rec1, m_rec2, m_consume],
        as_of=date(2026, 9, 5),
    )
    assert batch_stocks[1].current_quantity == Decimal("0.000")
    assert batch_stocks[2].current_quantity == Decimal("5.000")


def test_stock_calculation_writeoff_and_correction() -> None:
    """Проверяет списание брака и корректировки остатка (положительную и отрицательную)."""
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
    m_writeoff = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 3),
        item_id=1,
        location_id=1,
        type="writeoff",
        quantity=Decimal("2.000"),
        doc_number="WO-1",
        batch_id=1,
        reason="Истечение срока годности",
    )
    m_corr_neg = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 4),
        item_id=1,
        location_id=1,
        type="correction",
        quantity=Decimal("-1.500"),
        doc_number="CORR-NEG",
        batch_id=1,
        reason="Инвентаризационная недостача",
    )
    m_corr_pos = MovementSnapshot(
        id=4,
        operation_date=date(2026, 9, 5),
        item_id=1,
        location_id=1,
        type="correction",
        quantity=Decimal("0.500"),
        doc_number="CORR-POS",
        batch_id=1,
        reason="Инвентаризационный излишек",
    )

    balance = calculate_stock_balance(
        [batch],
        [m_rec, m_writeoff, m_corr_neg, m_corr_pos],
        as_of=date(2026, 9, 5),
    )
    # 10 - 2 - 1.5 + 0.5 = 7.000
    assert balance.current_stock == Decimal("7.000")
    assert balance.available_stock == Decimal("7.000")
