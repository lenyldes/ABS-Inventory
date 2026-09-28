"""Тесты для задачи 2.3: смена учётной партии в строке расхода и проверка годности."""

from datetime import date, datetime
from decimal import Decimal

from app.inventory.amendments_domain import (
    AllocationBatchChange,
    AmendmentOperation,
)
from app.inventory.amendments_service import simulate_amendment_set
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)


def _batch(
    b_id: int,
    unit_price: Decimal = Decimal("100.00"),
    expiry_date: date | None = date(2027, 1, 1),
) -> BatchSnapshot:
    return BatchSnapshot(
        id=b_id,
        item_id=1,
        location_id=1,
        batch_number=f"B-{b_id}",
        receipt_date=date(2026, 9, 1),
        expiry_date=expiry_date,
        unit_price=unit_price,
        receipt_doc_number=f"DOC-{b_id}",
        created_at=datetime(2026, 9, 1, 10, 0),
    )


def test_batch_swap_syncs_price_and_related_returns_without_fefo() -> None:
    """Смена партии строки расхода обновляет цену строки и возврат без авто-FEFO."""
    b1 = _batch(1, unit_price=Decimal("100.00"))
    b2 = _batch(2, unit_price=Decimal("180.00"))

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
    rec2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
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
        quantity=Decimal("4.000"),
        doc_number="CONS-3",
        allocations=(
            AllocationSnapshot(
                id=10,
                movement_id=3,
                batch_id=1,
                quantity=Decimal("4.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )
    ret = MovementSnapshot(
        id=4,
        operation_date=date(2026, 9, 3),
        created_at=datetime(2026, 9, 3, 10, 0),
        item_id=1,
        location_id=1,
        type="return",
        quantity=Decimal("1.000"),
        doc_number="RET-4",
        batch_id=1,
        parent_movement_id=3,
        parent_allocation_id=10,
    )

    op = AmendmentOperation(
        movement_id=3,
        action="update",
        allocation_batch_change=AllocationBatchChange(allocation_id=10, new_batch_id=2),
    )
    res = simulate_amendment_set(
        batches=[b1, b2],
        movements=[rec1, rec2, cons, ret],
        operations=[op],
        today=date(2026, 9, 10),
    )

    assert res.can_apply
    assert 4 in res.affected_operations
    proj_cons = next(m for m in res.projected_movements if m.id == 3)
    assert proj_cons.allocations[0].batch_id == 2
    assert proj_cons.allocations[0].unit_price == Decimal("180.00")

    proj_ret = next(m for m in res.projected_movements if m.id == 4)
    assert proj_ret.batch_id == 2


def test_expired_batch_rejection() -> None:
    """Назначение просроченной на дату расхода партии отклоняется блокером EXPIRED_BATCH."""
    b1 = _batch(1)
    b_expired = _batch(2, expiry_date=date(2026, 9, 1))

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
    rec2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
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
        quantity=Decimal("4.000"),
        doc_number="CONS-3",
        allocations=(
            AllocationSnapshot(
                id=10,
                movement_id=3,
                batch_id=1,
                quantity=Decimal("4.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )

    op = AmendmentOperation(
        movement_id=3,
        action="update",
        allocation_batch_change=AllocationBatchChange(allocation_id=10, new_batch_id=2),
    )
    res = simulate_amendment_set(
        batches=[b1, b_expired],
        movements=[rec1, rec2, cons],
        operations=[op],
        today=date(2026, 9, 10),
    )

    assert not res.can_apply
    bl = next(b for b in res.blockers if b.code == "EXPIRED_BATCH")
    assert bl.batch_id == 2
    assert bl.allocation_id == 10
