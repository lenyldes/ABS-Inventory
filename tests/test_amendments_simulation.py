"""Чистые модульные тесты для задачи 2.1: совместное исправление прихода и расхода."""

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


def _make_batch(
    batch_id: int = 1,
    item_id: int = 10,
    location_id: int = 100,
    quantity: Decimal = Decimal("10.000"),
    receipt_date: date = date(2026, 9, 1),
) -> BatchSnapshot:
    return BatchSnapshot(
        id=batch_id,
        item_id=item_id,
        location_id=location_id,
        batch_number=f"B-{batch_id}",
        receipt_date=receipt_date,
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
        receipt_doc_number=f"DOC-REC-{batch_id}",
        created_at=datetime(2026, 9, 1, 10, 0),
    )


def _make_receipt(
    movement_id: int = 1,
    batch_id: int = 1,
    quantity: Decimal = Decimal("10.000"),
    operation_date: date = date(2026, 9, 1),
) -> MovementSnapshot:
    return MovementSnapshot(
        id=movement_id,
        operation_date=operation_date,
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=10,
        location_id=100,
        type="receipt",
        quantity=quantity,
        doc_number=f"REC-{movement_id}",
        batch_id=batch_id,
    )


def _make_consume(
    movement_id: int = 2,
    batch_id: int = 1,
    quantity: Decimal = Decimal("10.000"),
    operation_date: date = date(2026, 9, 2),
    alloc_id: int = 50,
) -> MovementSnapshot:
    return MovementSnapshot(
        id=movement_id,
        operation_date=operation_date,
        created_at=datetime(2026, 9, 2, 10, 0),
        item_id=10,
        location_id=100,
        type="consume",
        quantity=quantity,
        doc_number=f"CONS-{movement_id}",
        allocations=(
            AllocationSnapshot(
                id=alloc_id,
                movement_id=movement_id,
                batch_id=batch_id,
                quantity=quantity,
                unit_price=Decimal("100.00"),
            ),
        ),
    )


def test_joint_decrease_impossible_sequentially() -> None:
    """Совместное уменьшение прихода и расхода с 10 до 5:
    поочерёдно уменьшение прихода невозможно из-за дефицита.
    """
    batch = _make_batch()
    rec = _make_receipt(quantity=Decimal("10.000"))
    cons = _make_consume(quantity=Decimal("10.000"))

    # Попытка уменьшить только приход до 5 при прежнем расходе 10 даёт исторический дефицит
    only_receipt_op = AmendmentOperation(
        movement_id=rec.id,
        action="update",
        quantity=Decimal("5.000"),
    )
    result_seq = simulate_amendment_set(
        batches=[batch],
        movements=[rec, cons],
        operations=[only_receipt_op],
        today=date(2026, 9, 10),
    )
    assert not result_seq.can_apply
    assert len(result_seq.blockers) == 1
    assert result_seq.blockers[0].code == "HISTORICAL_DEFICIT"
    assert result_seq.blockers[0].deficit_qty == Decimal("5.000")

    # Совместное применение набора: приход 5 и расход 5 проходит успешно
    joint_ops = [
        AmendmentOperation(
            movement_id=rec.id,
            action="update",
            quantity=Decimal("5.000"),
        ),
        AmendmentOperation(
            movement_id=cons.id,
            action="update",
            quantity=Decimal("5.000"),
            allocation_quantities=(
                AllocationQuantityChange(allocation_id=50, quantity=Decimal("5.000")),
            ),
        ),
    ]
    result_joint = simulate_amendment_set(
        batches=[batch],
        movements=[rec, cons],
        operations=joint_ops,
        today=date(2026, 9, 10),
    )
    assert result_joint.can_apply
    assert len(result_joint.blockers) == 0
    assert set(result_joint.affected_operations) == {rec.id, cons.id}


def test_joint_increase_impossible_sequentially() -> None:
    """Совместное увеличение прихода и расхода с 10 до 15:
    поочерёдно увеличение расхода невозможно из-за дефицита.
    """
    batch = _make_batch()
    rec = _make_receipt(quantity=Decimal("10.000"))
    cons = _make_consume(quantity=Decimal("10.000"))

    # Попытка увеличить только расход до 15 при приходе 10 даёт дефицит 5
    only_consume_op = AmendmentOperation(
        movement_id=cons.id,
        action="update",
        quantity=Decimal("15.000"),
        allocation_quantities=(
            AllocationQuantityChange(allocation_id=50, quantity=Decimal("15.000")),
        ),
    )
    result_seq = simulate_amendment_set(
        batches=[batch],
        movements=[rec, cons],
        operations=[only_consume_op],
        today=date(2026, 9, 10),
    )
    assert not result_seq.can_apply
    assert len(result_seq.blockers) == 1
    assert result_seq.blockers[0].code == "HISTORICAL_DEFICIT"
    assert result_seq.blockers[0].deficit_qty == Decimal("5.000")

    # Совместное увеличение прихода до 15 и расхода до 15 успешно
    joint_ops = [
        AmendmentOperation(
            movement_id=rec.id,
            action="update",
            quantity=Decimal("15.000"),
        ),
        AmendmentOperation(
            movement_id=cons.id,
            action="update",
            quantity=Decimal("15.000"),
            allocation_quantities=(
                AllocationQuantityChange(allocation_id=50, quantity=Decimal("15.000")),
            ),
        ),
    ]
    result_joint = simulate_amendment_set(
        batches=[batch],
        movements=[rec, cons],
        operations=joint_ops,
        today=date(2026, 9, 10),
    )
    assert result_joint.can_apply
    assert len(result_joint.blockers) == 0


def test_simulation_does_not_mutate_original_snapshots() -> None:
    """Симуляция не меняет исходные кортежи и структуры движений и партий."""
    batch = _make_batch()
    rec = _make_receipt(quantity=Decimal("10.000"))
    cons = _make_consume(quantity=Decimal("10.000"))

    ops = [
        AmendmentOperation(
            movement_id=rec.id,
            action="update",
            quantity=Decimal("5.000"),
        ),
        AmendmentOperation(
            movement_id=cons.id,
            action="update",
            quantity=Decimal("5.000"),
            allocation_quantities=(
                AllocationQuantityChange(allocation_id=50, quantity=Decimal("5.000")),
            ),
        ),
    ]
    simulate_amendment_set(
        batches=[batch],
        movements=[rec, cons],
        operations=ops,
        today=date(2026, 9, 10),
    )

    # Исходные объекты сохранили значения
    assert rec.quantity == Decimal("10.000")
    assert cons.quantity == Decimal("10.000")
    assert cons.allocations[0].quantity == Decimal("10.000")
    assert batch.receipt_doc_number == "DOC-REC-1"
