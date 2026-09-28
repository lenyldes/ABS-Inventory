"""Тесты для задачи 2.2: проверка возвратов при отменах и уменьшении расхода."""

from datetime import date, datetime
from decimal import Decimal

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


def _batch(b_id: int = 1) -> BatchSnapshot:
    return BatchSnapshot(
        id=b_id,
        item_id=1,
        location_id=1,
        batch_number=f"B-{b_id}",
        receipt_date=date(2026, 9, 1),
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("150.00"),
        receipt_doc_number=f"DOC-{b_id}",
        created_at=datetime(2026, 9, 1, 10, 0),
    )


def test_cancelled_consume_requires_cancelling_all_active_returns() -> None:
    """Отмена расхода блокируется при наличии активного возврата, пока он не отменён."""
    b = _batch(1)
    rec = MovementSnapshot(
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
                id=200,
                movement_id=2,
                batch_id=1,
                quantity=Decimal("5.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )
    ret = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 3),
        created_at=datetime(2026, 9, 3, 10, 0),
        item_id=1,
        location_id=1,
        type="return",
        quantity=Decimal("2.000"),
        doc_number="RET-3",
        batch_id=1,
        parent_movement_id=2,
        parent_allocation_id=200,
    )

    # 1. Отменяем только расход: получаем блокер UNCANCELLED_RETURNS
    res_only_cons = simulate_amendment_set(
        batches=[b],
        movements=[rec, cons, ret],
        operations=[AmendmentOperation(movement_id=2, action="cancel")],
        today=date(2026, 9, 10),
    )
    assert not res_only_cons.can_apply
    bl = next(b for b in res_only_cons.blockers if b.code == "UNCANCELLED_RETURNS")
    assert bl.movement_id == 2
    assert bl.dependent_movement_id == 3

    # 2. Отменяем и расход, и возврат в одном наборе: успешно
    res_both = simulate_amendment_set(
        batches=[b],
        movements=[rec, cons, ret],
        operations=[
            AmendmentOperation(movement_id=2, action="cancel"),
            AmendmentOperation(movement_id=3, action="cancel"),
        ],
        today=date(2026, 9, 10),
    )
    assert res_both.can_apply
    assert len(res_both.blockers) == 0


def test_excess_return_when_consume_quantity_is_reduced() -> None:
    """Уменьшение расхода ниже объёма уже сделанного возврата даёт EXCESS_RETURN."""
    b = _batch(1)
    rec = MovementSnapshot(
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
                id=200,
                movement_id=2,
                batch_id=1,
                quantity=Decimal("5.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )
    ret = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 3),
        created_at=datetime(2026, 9, 3, 10, 0),
        item_id=1,
        location_id=1,
        type="return",
        quantity=Decimal("4.000"),
        doc_number="RET-3",
        batch_id=1,
        parent_movement_id=2,
        parent_allocation_id=200,
    )

    op = AmendmentOperation(
        movement_id=2,
        action="update",
        quantity=Decimal("2.000"),
        allocation_quantities=(
            AllocationQuantityChange(allocation_id=200, quantity=Decimal("2.000")),
        ),
    )
    res = simulate_amendment_set(
        batches=[b],
        movements=[rec, cons, ret],
        operations=[op],
        today=date(2026, 9, 10),
    )

    assert not res.can_apply
    bl = next(b for b in res.blockers if b.code == "EXCESS_RETURN")
    assert bl.dependent_movement_id == 3
    assert bl.allocation_id == 200
    assert bl.deficit_qty == Decimal("2.000")


def test_invalid_return_date_earlier_than_consume() -> None:
    """Дата возврата раньше даты расхода формирует блокер INVALID_RETURN_DATE."""
    b = _batch(1)
    rec = MovementSnapshot(
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
                id=200,
                movement_id=2,
                batch_id=1,
                quantity=Decimal("5.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )
    ret = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 3),
        created_at=datetime(2026, 9, 3, 10, 0),
        item_id=1,
        location_id=1,
        type="return",
        quantity=Decimal("2.000"),
        doc_number="RET-3",
        batch_id=1,
        parent_movement_id=2,
        parent_allocation_id=200,
    )

    op = AmendmentOperation(
        movement_id=2,
        action="update",
        operation_date=date(2026, 9, 4),
    )
    res = simulate_amendment_set(
        batches=[b],
        movements=[rec, cons, ret],
        operations=[op],
        today=date(2026, 9, 10),
    )

    assert not res.can_apply
    bl = next(b for b in res.blockers if b.code == "INVALID_RETURN_DATE")
    assert bl.dependent_movement_id == 3
