"""Тесты для задачи 2.2: проверка дефицита при отменах и переносе дат."""

from datetime import date, datetime
from decimal import Decimal

from app.inventory.amendments_domain import AmendmentOperation
from app.inventory.amendments_service import simulate_amendment_set
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)


def _batch(b_id: int = 1, rec_date: date = date(2026, 9, 1)) -> BatchSnapshot:
    return BatchSnapshot(
        id=b_id,
        item_id=1,
        location_id=1,
        batch_number=f"B-{b_id}",
        receipt_date=rec_date,
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("150.00"),
        receipt_doc_number=f"DOC-{b_id}",
        created_at=datetime(2026, 9, 1, 10, 0),
    )


def test_cancel_receipt_causes_deficit_with_exact_blocker_fields() -> None:
    """Отмена прихода создаёт дефицит в последующем расходе с точными ID, датой и дефицитом."""
    b = _batch(1)
    rec = MovementSnapshot(
        id=10,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-10",
        batch_id=1,
    )
    cons = MovementSnapshot(
        id=20,
        operation_date=date(2026, 9, 3),
        created_at=datetime(2026, 9, 3, 10, 0),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("8.000"),
        doc_number="CONS-20",
        allocations=(
            AllocationSnapshot(
                id=100,
                movement_id=20,
                batch_id=1,
                quantity=Decimal("8.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )

    cancel_op = AmendmentOperation(movement_id=10, action="cancel")
    res = simulate_amendment_set(
        batches=[b],
        movements=[rec, cons],
        operations=[cancel_op],
        today=date(2026, 9, 10),
    )

    assert not res.can_apply
    assert len(res.blockers) == 1
    blocker = res.blockers[0]
    assert blocker.code == "HISTORICAL_DEFICIT"
    assert blocker.dependent_movement_id == 20
    assert blocker.deficit_date == date(2026, 9, 3)
    assert blocker.deficit_qty == Decimal("8.000")
    assert blocker.batch_id == 1


def test_postponing_receipt_date_causes_retrospective_deficit() -> None:
    """Перенос даты прихода вперёд создаёт дефицит на дату промежуточного расхода."""
    b = _batch(1, rec_date=date(2026, 9, 1))
    rec = MovementSnapshot(
        id=10,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-10",
        batch_id=1,
    )
    cons = MovementSnapshot(
        id=20,
        operation_date=date(2026, 9, 3),
        created_at=datetime(2026, 9, 3, 10, 0),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("6.000"),
        doc_number="CONS-20",
        allocations=(
            AllocationSnapshot(
                id=100,
                movement_id=20,
                batch_id=1,
                quantity=Decimal("6.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )

    move_date_op = AmendmentOperation(
        movement_id=10,
        action="update",
        operation_date=date(2026, 9, 5),
    )
    res = simulate_amendment_set(
        batches=[b],
        movements=[rec, cons],
        operations=[move_date_op],
        today=date(2026, 9, 10),
    )

    assert not res.can_apply
    assert len(res.blockers) == 1
    assert res.blockers[0].code == "HISTORICAL_DEFICIT"
    assert res.blockers[0].dependent_movement_id == 20
    assert res.blockers[0].deficit_date == date(2026, 9, 3)
    assert res.blockers[0].deficit_qty == Decimal("6.000")


def test_future_operation_date_blocker() -> None:
    """Операция с датой в будущем фиксируется как блокер FUTURE_DATE."""
    b = _batch(1)
    rec = MovementSnapshot(
        id=10,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-10",
        batch_id=1,
    )
    op = AmendmentOperation(
        movement_id=10,
        action="update",
        operation_date=date(2026, 9, 15),
    )
    res = simulate_amendment_set(
        batches=[b],
        movements=[rec],
        operations=[op],
        today=date(2026, 9, 10),
    )
    assert not res.can_apply
    assert any(bl.code == "FUTURE_DATE" for bl in res.blockers)
