"""Проверка зависимостей: возвраты, сроки годности и перенос прихода на другой объект."""

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from app.inventory.amendments_domain import AmendmentBlocker, AmendmentOperation
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)

_ZERO = Decimal("0.000")


def check_receipt_relocation(
    projected_movements: Sequence[MovementSnapshot],
    original_movements: Sequence[MovementSnapshot],
    operations: Sequence[AmendmentOperation],
    blockers: list[AmendmentBlocker],
) -> None:
    """Проверяет отсутствие зависимых операций на старом объекте при переносе прихода."""
    orig_map = {m.id: m for m in original_movements}
    proj_map = {m.id: m for m in projected_movements}

    for op in operations:
        if op.action != "update":
            continue
        orig_m = orig_map.get(op.movement_id)
        proj_m = proj_map.get(op.movement_id)
        if not orig_m or not proj_m or orig_m.type != "receipt":
            continue
        if orig_m.location_id == proj_m.location_id:
            continue

        b_id = orig_m.batch_id
        old_loc = orig_m.location_id
        dep_ops: list[int] = []

        for pm in projected_movements:
            if pm.id == orig_m.id or pm.status != "active" or pm.location_id != old_loc:
                continue
            if pm.type == "consume" and any(a.batch_id == b_id for a in pm.allocations):
                if pm.id is not None:
                    dep_ops.append(pm.id)
            elif pm.batch_id == b_id and pm.id is not None:
                dep_ops.append(pm.id)

        if dep_ops:
            blockers.append(
                AmendmentBlocker(
                    code="DEPENDENT_OPERATIONS_ON_OLD_LOCATION",
                    message=(
                        f"Перемещение прихода отклонено: партия {b_id} имеет "
                        f"зависимые операции на объекте"
                    ),
                    movement_id=orig_m.id,
                    batch_id=b_id,
                    details={"dependent_movement_ids": dep_ops, "old_location_id": old_loc},
                )
            )


def check_returns_and_cancellations(
    projected_movements: Sequence[MovementSnapshot],
    blockers: list[AmendmentBlocker],
) -> None:
    """Проверяет возвраты: активный родительский расход, даты и доступный лимит возврата."""
    cancelled_consumes = {
        m.id for m in projected_movements if m.type == "consume" and m.status == "cancelled"
    }
    active_consumes = {
        m.id: m for m in projected_movements if m.type == "consume" and m.status == "active"
    }

    active_allocs: dict[int, tuple[AllocationSnapshot, MovementSnapshot]] = {}
    for cm in active_consumes.values():
        for alloc in cm.allocations:
            if alloc.id is not None:
                active_allocs[alloc.id] = (alloc, cm)

    for pm in projected_movements:
        if (
            pm.type == "return"
            and pm.status == "active"
            and pm.parent_movement_id in cancelled_consumes
        ):
            blockers.append(
                AmendmentBlocker(
                    code="UNCANCELLED_RETURNS",
                    message=f"Исходный расход {pm.parent_movement_id} отменён, но возврат активен",
                    movement_id=pm.parent_movement_id,
                    dependent_movement_id=pm.id,
                    details={"return_movement_id": pm.id},
                )
            )

    returns_by_alloc: dict[int, list[MovementSnapshot]] = defaultdict(list)
    for pm in projected_movements:
        if pm.type == "return" and pm.status == "active" and pm.parent_allocation_id is not None:
            returns_by_alloc[pm.parent_allocation_id].append(pm)

    for alloc_id, rets in returns_by_alloc.items():
        if alloc_id not in active_allocs:
            for ret in rets:
                blockers.append(
                    AmendmentBlocker(
                        code="MISSING_PARENT_CONSUME",
                        message=(
                            f"Возврат {ret.id} ссылается на неактивный или отсутствующий расход"
                        ),
                        movement_id=ret.id,
                        dependent_movement_id=ret.parent_movement_id,
                        allocation_id=alloc_id,
                    )
                )
            continue

        alloc, parent_consume = active_allocs[alloc_id]
        for ret in rets:
            if ret.operation_date < parent_consume.operation_date:
                blockers.append(
                    AmendmentBlocker(
                        code="INVALID_RETURN_DATE",
                        message=(
                            f"Дата возврата {ret.operation_date.isoformat()} не может "
                            f"предшествовать расходу {parent_consume.operation_date.isoformat()}"
                        ),
                        movement_id=parent_consume.id,
                        dependent_movement_id=ret.id,
                        allocation_id=alloc_id,
                        deficit_date=ret.operation_date,
                    )
                )

        total_returned = sum((r.quantity for r in rets), _ZERO)
        if total_returned > alloc.quantity:
            excess = total_returned - alloc.quantity
            for ret in rets:
                blockers.append(
                    AmendmentBlocker(
                        code="EXCESS_RETURN",
                        message=(
                            f"Сумма возвратов превышает количество строки {alloc_id} на {excess}"
                        ),
                        movement_id=parent_consume.id,
                        dependent_movement_id=ret.id,
                        allocation_id=alloc_id,
                        deficit_qty=excess,
                        details={
                            "max_allowed_return": str(alloc.quantity),
                            "requested_return": str(total_returned),
                        },
                    )
                )


def check_batch_expiries(
    projected_movements: Sequence[MovementSnapshot],
    projected_batches: Sequence[BatchSnapshot],
    blockers: list[AmendmentBlocker],
) -> None:
    """Проверяет срок годности партии на дату расхода."""
    batch_map = {b.id: b for b in projected_batches}
    for m in projected_movements:
        if m.type != "consume" or m.status != "active":
            continue
        for alloc in m.allocations:
            b = batch_map.get(alloc.batch_id)
            if b and b.expiry_date is not None and b.expiry_date < m.operation_date:
                blockers.append(
                    AmendmentBlocker(
                        code="EXPIRED_BATCH",
                        message=(
                            f"Партия {b.id} просрочена ({b.expiry_date}) на дату расхода "
                            f"{m.operation_date}"
                        ),
                        movement_id=m.id,
                        batch_id=b.id,
                        allocation_id=alloc.id,
                        details={
                            "expiry_date": b.expiry_date.isoformat(),
                            "operation_date": m.operation_date.isoformat(),
                        },
                    )
                )
