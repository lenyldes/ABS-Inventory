"""Логика симуляции изменений для операций расхода (consume)."""

from collections.abc import Sequence
from decimal import Decimal

from app.inventory.amendments_domain import (
    AllocationBatchChange,
    AllocationQuantityChange,
    AmendmentOperation,
)
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)
from app.inventory.exceptions import (
    AmendmentValidationError,
    EntityNotFoundError,
)

_ZERO = Decimal("0.000")


def update_consume_allocations(
    movement: MovementSnapshot,
    allocation_quantities: Sequence[AllocationQuantityChange] | None,
    allocation_batch_change: AllocationBatchChange | None,
    batches_by_id: dict[int, BatchSnapshot],
    new_quantity: Decimal,
) -> tuple[tuple[AllocationSnapshot, ...], int | None]:
    """Обновляет строки распределения расхода: количества и смену партии."""
    allocs = list(movement.allocations)
    alloc_map = {a.id: a for a in allocs if a.id is not None}

    if allocation_quantities is not None:
        qty_map: dict[int, Decimal] = {}
        for aq in allocation_quantities:
            if aq.allocation_id not in alloc_map:
                raise AmendmentValidationError(
                    f"Строка распределения {aq.allocation_id} не принадлежит расходу {movement.id}",
                    code="ALLOCATION_NOT_FOUND",
                    details={"allocation_id": aq.allocation_id, "movement_id": movement.id},
                )
            if aq.quantity <= _ZERO:
                raise AmendmentValidationError(
                    f"Количество строки {aq.allocation_id} должно быть строго больше нуля",
                    code="INVALID_ALLOCATION_QUANTITY",
                    details={"allocation_id": aq.allocation_id, "quantity": str(aq.quantity)},
                )
            qty_map[aq.allocation_id] = aq.quantity

        updated_allocs: list[AllocationSnapshot] = []
        for a in allocs:
            if a.id in qty_map:
                updated_allocs.append(
                    AllocationSnapshot(
                        id=a.id,
                        movement_id=a.movement_id,
                        batch_id=a.batch_id,
                        quantity=qty_map[a.id],
                        unit_price=a.unit_price,
                    )
                )
            else:
                updated_allocs.append(a)

        sum_qty = sum((a.quantity for a in updated_allocs), _ZERO)
        if sum_qty != new_quantity:
            raise AmendmentValidationError(
                f"Сумма строк распределения ({sum_qty}) не равна "
                f"количеству расхода ({new_quantity})",
                code="ALLOCATION_SUM_MISMATCH",
                details={"sum_allocations": str(sum_qty), "movement_quantity": str(new_quantity)},
            )
        allocs = updated_allocs
        alloc_map = {a.id: a for a in allocs if a.id is not None}

    updated_batch_alloc_id: int | None = None
    if allocation_batch_change is not None:
        abc = allocation_batch_change
        if abc.allocation_id not in alloc_map:
            raise AmendmentValidationError(
                f"Строка распределения {abc.allocation_id} не найдена в расходе {movement.id}",
                code="ALLOCATION_NOT_FOUND",
                details={"allocation_id": abc.allocation_id, "movement_id": movement.id},
            )
        if abc.new_batch_id not in batches_by_id:
            raise EntityNotFoundError("Batch", abc.new_batch_id)

        new_batch = batches_by_id[abc.new_batch_id]
        if new_batch.item_id != movement.item_id or new_batch.location_id != movement.location_id:
            raise AmendmentValidationError(
                f"Партия {abc.new_batch_id} не принадлежит товару/объекту расхода",
                code="BATCH_ITEM_LOCATION_MISMATCH",
                details={"new_batch_id": abc.new_batch_id, "movement_id": movement.id},
            )

        target = alloc_map[abc.allocation_id]
        replaced_alloc = AllocationSnapshot(
            id=target.id,
            movement_id=target.movement_id,
            batch_id=abc.new_batch_id,
            quantity=target.quantity,
            unit_price=new_batch.unit_price,
        )
        allocs = [replaced_alloc if a.id == abc.allocation_id else a for a in allocs]
        updated_batch_alloc_id = abc.allocation_id

    return tuple(allocs), updated_batch_alloc_id


def apply_consume_amendment(
    mv: MovementSnapshot,
    op: AmendmentOperation,
    batches_map: dict[int, BatchSnapshot],
    movements_map: dict[int, MovementSnapshot],
    implicitly_affected: set[int],
) -> None:
    """Применяет изменение параметров расхода и обновляет связанные возвраты."""
    new_date = op.operation_date if op.operation_date is not None else mv.operation_date
    new_doc = op.doc_number if op.doc_number is not None else mv.doc_number
    new_qty = op.quantity if op.quantity is not None else mv.quantity

    if op.quantity is not None and op.quantity != mv.quantity and not op.allocation_quantities:
        raise AmendmentValidationError(
            "При изменении quantity расхода обязателен allocation_quantities",
            code="MISSING_ALLOCATION_QUANTITIES",
        )

    new_allocs, changed_alloc_id = update_consume_allocations(
        movement=mv,
        allocation_quantities=op.allocation_quantities,
        allocation_batch_change=op.allocation_batch_change,
        batches_by_id=batches_map,
        new_quantity=new_qty,
    )

    if changed_alloc_id is not None and op.allocation_batch_change is not None:
        new_b_id = op.allocation_batch_change.new_batch_id
        for other_id, other_mv in list(movements_map.items()):
            if (
                other_mv.type == "return"
                and other_mv.parent_allocation_id == changed_alloc_id
                and other_mv.status == "active"
            ):
                movements_map[other_id] = MovementSnapshot(
                    id=other_mv.id,
                    operation_date=other_mv.operation_date,
                    created_at=other_mv.created_at,
                    item_id=other_mv.item_id,
                    location_id=other_mv.location_id,
                    type=other_mv.type,
                    quantity=other_mv.quantity,
                    doc_number=other_mv.doc_number,
                    batch_id=new_b_id,
                    reason=other_mv.reason,
                    parent_movement_id=other_mv.parent_movement_id,
                    parent_allocation_id=other_mv.parent_allocation_id,
                    purchase_order_id=other_mv.purchase_order_id,
                    supplier_id=other_mv.supplier_id,
                    status=other_mv.status,
                    allocations=other_mv.allocations,
                )
                implicitly_affected.add(other_id)

    movements_map[mv.id] = MovementSnapshot(
        id=mv.id,
        operation_date=new_date,
        created_at=mv.created_at,
        item_id=mv.item_id,
        location_id=mv.location_id,
        type=mv.type,
        quantity=new_qty,
        doc_number=new_doc,
        batch_id=mv.batch_id,
        reason=mv.reason,
        parent_movement_id=mv.parent_movement_id,
        parent_allocation_id=mv.parent_allocation_id,
        purchase_order_id=mv.purchase_order_id,
        supplier_id=mv.supplier_id,
        status=mv.status,
        allocations=new_allocs,
    )
