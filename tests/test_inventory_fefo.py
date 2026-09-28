"""Модульные тесты FEFO-распределения и предупреждений fefo_deviation."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)
from app.inventory.exceptions import InsufficientStockError
from app.inventory.fefo import allocate_fefo, detect_fefo_deviation


def _batch(
    b_id: int,
    b_num: str,
    rec_date: date,
    exp_date: date | None,
    created_at: datetime | None = None,
) -> BatchSnapshot:
    return BatchSnapshot(
        id=b_id,
        item_id=1,
        location_id=1,
        batch_number=b_num,
        receipt_date=rec_date,
        expiry_date=exp_date,
        unit_price=Decimal("150.00"),
        receipt_doc_number=f"DOC-{b_id}",
        created_at=created_at or datetime(2026, 9, 1, 10, 0),
    )


def test_fefo_allocation_across_multiple_batches() -> None:
    """Проверяет распределение расхода по нескольким партиям в порядке FEFO."""
    b1 = _batch(1, "B1", date(2026, 9, 1), date(2026, 10, 10))
    b2 = _batch(2, "B2", date(2026, 9, 1), date(2026, 10, 20))

    m_rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("3.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    m_rec2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("4.000"),
        doc_number="REC-2",
        batch_id=2,
    )

    allocs = allocate_fefo(
        requested_qty=Decimal("5.000"),
        batches=[b1, b2],
        movements_prior=[m_rec1, m_rec2],
        operation_date=date(2026, 9, 5),
    )
    # 3.000 из b1 (ранний срок), 2.000 из b2
    assert len(allocs) == 2
    assert allocs[0].batch_id == 1
    assert allocs[0].quantity == Decimal("3.000")
    assert allocs[1].batch_id == 2
    assert allocs[1].quantity == Decimal("2.000")


def test_fefo_equal_expiry_dates_uses_receipt_and_created_at() -> None:
    """При равных сроках годности FEFO выбирает более раннее поступление."""
    b1 = _batch(
        1,
        "B1",
        date(2026, 9, 1),
        date(2026, 10, 10),
        created_at=datetime(2026, 9, 1, 9, 0),
    )
    b2 = _batch(
        2,
        "B2",
        date(2026, 9, 2),
        date(2026, 10, 10),
        created_at=datetime(2026, 9, 2, 9, 0),
    )

    m_rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    m_rec2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 2),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="REC-2",
        batch_id=2,
    )

    allocs = allocate_fefo(
        requested_qty=Decimal("3.000"),
        batches=[b1, b2],
        movements_prior=[m_rec1, m_rec2],
        operation_date=date(2026, 9, 5),
    )
    assert len(allocs) == 1
    assert allocs[0].batch_id == 1
    assert allocs[0].quantity == Decimal("3.000")


def test_fefo_skips_expired_batch_and_raises_on_insufficient_stock() -> None:
    """FEFO не списывает просроченную партию и падает при нехватке доступного остатка."""
    b_exp = _batch(1, "B-EXP", date(2026, 8, 1), date(2026, 9, 1))
    b_good = _batch(2, "B-GOOD", date(2026, 9, 1), date(2026, 10, 1))

    m_rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 8, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    m_rec2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("3.000"),
        doc_number="REC-2",
        batch_id=2,
    )

    # На дату 2026-09-05 партия 1 просрочена. Доступно только 3.000 из партии 2.
    with pytest.raises(InsufficientStockError) as exc_info:
        allocate_fefo(
            requested_qty=Decimal("4.000"),
            batches=[b_exp, b_good],
            movements_prior=[m_rec1, m_rec2],
            operation_date=date(2026, 9, 5),
        )
    assert exc_info.value.details["available"] == "3.000"


def test_fefo_deviation_detection_and_preservation_of_allocations() -> None:
    """Проверяет появление fefo_deviation при позднем приходе и сохранение распределения."""
    # Исходно на 2026-09-05 была доступна только партия b2 со сроком 2026-10-20
    b2 = _batch(2, "B2", date(2026, 9, 1), date(2026, 10, 20))
    m_rec2 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-2",
        batch_id=2,
    )
    m_consume = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 5),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("4.000"),
        doc_number="CONS-1",
        allocations=(
            AllocationSnapshot(
                batch_id=2,
                quantity=Decimal("4.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )

    # До позднего прихода расход идеально соответствует FEFO
    warnings_before = detect_fefo_deviation(
        consume_movement=m_consume,
        batches=[b2],
        movements_prior=[m_rec2],
    )
    assert warnings_before == []

    # Теперь задним числом регистрируется партия b1 (срок 2026-09-25 - раньше b2!) на 2026-09-02
    b1 = _batch(1, "B1", date(2026, 9, 2), date(2026, 9, 25))
    m_rec1 = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 2),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="REC-1",
        batch_id=1,
    )

    # При оценке с учётом актуальной истории:
    warnings_after = detect_fefo_deviation(
        consume_movement=m_consume,
        batches=[b1, b2],
        movements_prior=[m_rec2, m_rec1],
    )
    assert len(warnings_after) == 1
    w = warnings_after[0]
    assert w.code == "fefo_deviation"
    assert w.details["actual_batch_ids"] == [2]
    assert w.details["fefo_batch_ids"] == [1]

    # Сохранённые allocations у расхода остаются неизменными (партия 2)
    assert len(m_consume.allocations) == 1
    assert m_consume.allocations[0].batch_id == 2
