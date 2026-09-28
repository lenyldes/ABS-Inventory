"""Тесты для задачи 2.3: проверка строк и количеств распределения расхода."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.inventory.amendments_domain import (
    AllocationQuantityChange,
    AmendmentOperation,
)
from app.inventory.amendments_service import simulate_amendment_set
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)
from app.inventory.exceptions import AmendmentValidationError


def _batch(b_id: int) -> BatchSnapshot:
    return BatchSnapshot(
        id=b_id,
        item_id=1,
        location_id=1,
        batch_number=f"B-{b_id}",
        receipt_date=date(2026, 9, 1),
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
        receipt_doc_number=f"DOC-{b_id}",
        created_at=datetime(2026, 9, 1, 10, 0),
    )


def test_multi_batch_consume_partial_allocation_update() -> None:
    """Уменьшение многопартийного расхода с 5 до 4 с явным указанием одной строки."""
    b1 = _batch(1)
    b2 = _batch(2)

    rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    rec2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="REC-2",
        batch_id=2,
    )
    cons = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 2),
        created_at=datetime(2026, 9, 2, 10, 0),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("5.000"),
        doc_number="CONS-3",
        allocations=(
            AllocationSnapshot(
                id=10,
                movement_id=3,
                batch_id=1,
                quantity=Decimal("3.000"),
                unit_price=Decimal("100.00"),
            ),
            AllocationSnapshot(
                id=11,
                movement_id=3,
                batch_id=2,
                quantity=Decimal("2.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )

    op = AmendmentOperation(
        movement_id=3,
        action="update",
        quantity=Decimal("4.000"),
        allocation_quantities=(
            AllocationQuantityChange(allocation_id=10, quantity=Decimal("2.000")),
        ),
    )
    res = simulate_amendment_set(
        batches=[b1, b2],
        movements=[rec1, rec2, cons],
        operations=[op],
        today=date(2026, 9, 10),
    )

    assert res.can_apply
    assert len(res.blockers) == 0
    proj_cons = next(m for m in res.projected_movements if m.id == 3)
    assert proj_cons.quantity == Decimal("4.000")
    alloc_map = {a.id: a.quantity for a in proj_cons.allocations}
    assert alloc_map[10] == Decimal("2.000")
    assert alloc_map[11] == Decimal("2.000")


def test_allocation_sum_mismatch_raises_validation_error() -> None:
    """Несовпадение суммы строк распределения с новым количеством расхода отклоняется."""
    b1 = _batch(1)
    rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    cons = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 2),
        created_at=datetime(2026, 9, 2, 10, 0),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("5.000"),
        doc_number="CONS-2",
        allocations=(
            AllocationSnapshot(
                id=10,
                movement_id=2,
                batch_id=1,
                quantity=Decimal("5.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )

    op = AmendmentOperation(
        movement_id=2,
        action="update",
        quantity=Decimal("4.000"),
        allocation_quantities=(
            AllocationQuantityChange(allocation_id=10, quantity=Decimal("3.000")),
        ),
    )
    with pytest.raises(AmendmentValidationError) as exc:
        simulate_amendment_set(
            batches=[b1],
            movements=[rec1, cons],
            operations=[op],
            today=date(2026, 9, 10),
        )
    assert exc.value.code == "ALLOCATION_SUM_MISMATCH"


def test_missing_allocation_quantities_on_consume_quantity_change() -> None:
    """Изменение количества расхода без allocation_quantities отклоняется."""
    b1 = _batch(1)
    rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    cons = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 2),
        created_at=datetime(2026, 9, 2, 10, 0),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("5.000"),
        doc_number="CONS-2",
        allocations=(
            AllocationSnapshot(
                id=10,
                movement_id=2,
                batch_id=1,
                quantity=Decimal("5.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )

    op = AmendmentOperation(
        movement_id=2,
        action="update",
        quantity=Decimal("3.000"),
    )
    with pytest.raises(AmendmentValidationError) as exc:
        simulate_amendment_set(
            batches=[b1],
            movements=[rec1, cons],
            operations=[op],
            today=date(2026, 9, 10),
        )
    assert exc.value.code == "MISSING_ALLOCATION_QUANTITIES"
