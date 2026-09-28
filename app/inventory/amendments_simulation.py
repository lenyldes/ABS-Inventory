"""Применение набора исправлений к снимкам движений и партий без записи в БД."""

from collections.abc import Callable, Sequence
from decimal import Decimal

from app.inventory.amendments_consume_simulation import apply_consume_amendment
from app.inventory.amendments_domain import AmendmentOperation
from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.inventory.exceptions import (
    AmendmentValidationError,
    EntityNotFoundError,
)

_ZERO = Decimal("0.000")


def _apply_receipt_amendment(
    mv: MovementSnapshot,
    op: AmendmentOperation,
    batches_map: dict[int, BatchSnapshot],
    movements_map: dict[int, MovementSnapshot],
    new_date: any,
    new_doc: str,
    new_loc_id: int,
    new_qty: Decimal,
) -> None:
    """Применяет изменения поступления (receipt) и синхронизирует метаданные партии."""
    movements_map[mv.id] = MovementSnapshot(
        id=mv.id,
        operation_date=new_date,
        created_at=mv.created_at,
        item_id=mv.item_id,
        location_id=new_loc_id,
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
        allocations=mv.allocations,
    )

    if mv.batch_id is not None and mv.batch_id in batches_map:
        old_b = batches_map[mv.batch_id]
        batches_map[mv.batch_id] = BatchSnapshot(
            id=old_b.id,
            item_id=old_b.item_id,
            location_id=new_loc_id,
            batch_number=old_b.batch_number,
            receipt_date=new_date,
            expiry_date=old_b.expiry_date,
            unit_price=old_b.unit_price,
            receipt_doc_number=new_doc,
            created_at=old_b.created_at,
        )


def _validate_operation_fields(mv: MovementSnapshot, op: AmendmentOperation) -> None:
    """Проверяет допустимость полей для конкретного типа движения."""
    if op.raw_fields and "sku" in op.raw_fields:
        raise AmendmentValidationError("Смена SKU запрещена", code="CANNOT_CHANGE_SKU")

    has_location_edit = (
        op.location_id is not None
        or op.location_code is not None
        or (op.raw_fields and "location" in op.raw_fields)
    )
    if mv.type != "receipt" and has_location_edit:
        raise AmendmentValidationError(
            f"Смена объекта запрещена для типа движения '{mv.type}'",
            code="INVALID_LOCATION_CHANGE",
        )

    has_alloc_edit = (
        op.allocation_quantities is not None
        or op.allocation_batch_change is not None
        or (
            op.raw_fields
            and ("allocation_quantities" in op.raw_fields or "allocation_id" in op.raw_fields)
        )
    )
    if mv.type != "consume" and has_alloc_edit:
        raise AmendmentValidationError(
            "Строки распределения применимы только для расхода ('consume')",
            code="INVALID_ALLOCATION_FIELDS",
        )


def apply_amendments_to_snapshots(
    batches: Sequence[BatchSnapshot],
    movements: Sequence[MovementSnapshot],
    operations: Sequence[AmendmentOperation],
    *,
    location_resolver: Callable[[str], int | None] | None = None,
) -> tuple[tuple[BatchSnapshot, ...], tuple[MovementSnapshot, ...], set[int], set[int]]:
    """Применяет операции правки к доменным копиям движений и партий."""
    batches_map = {b.id: b for b in batches}
    movements_map = {m.id: m for m in movements}
    directly_affected: set[int] = set()
    implicitly_affected: set[int] = set()

    for op in operations:
        if op.movement_id not in movements_map:
            raise EntityNotFoundError("Movement", op.movement_id)

        mv = movements_map[op.movement_id]
        directly_affected.add(mv.id)

        if op.action == "cancel":
            movements_map[mv.id] = MovementSnapshot(
                id=mv.id,
                operation_date=mv.operation_date,
                created_at=mv.created_at,
                item_id=mv.item_id,
                location_id=mv.location_id,
                type=mv.type,
                quantity=mv.quantity,
                doc_number=mv.doc_number,
                batch_id=mv.batch_id,
                reason=mv.reason,
                parent_movement_id=mv.parent_movement_id,
                parent_allocation_id=mv.parent_allocation_id,
                purchase_order_id=mv.purchase_order_id,
                supplier_id=mv.supplier_id,
                status="cancelled",
                allocations=mv.allocations,
            )
            continue

        if op.action != "update":
            raise AmendmentValidationError(
                f"Неизвестное действие: '{op.action}'", code="UNKNOWN_ACTION"
            )

        _validate_operation_fields(mv, op)

        new_date = op.operation_date if op.operation_date is not None else mv.operation_date
        new_doc = op.doc_number if op.doc_number is not None else mv.doc_number
        new_qty = op.quantity if op.quantity is not None else mv.quantity

        if mv.type != "correction" and new_qty <= _ZERO:
            raise AmendmentValidationError(
                f"Количество движения '{mv.type}' должно быть строго больше нуля",
                code="INVALID_QUANTITY",
            )
        if mv.type == "correction" and new_qty == _ZERO:
            raise AmendmentValidationError(
                "Количество корректировки не может быть равно нулю",
                code="ZERO_QUANTITY",
            )

        new_loc_id = mv.location_id
        if op.location_id is not None:
            new_loc_id = op.location_id
        elif op.location_code is not None and location_resolver:
            resolved = location_resolver(op.location_code)
            if resolved is not None:
                new_loc_id = resolved

        if mv.type == "consume":
            apply_consume_amendment(
                mv=mv,
                op=op,
                batches_map=batches_map,
                movements_map=movements_map,
                implicitly_affected=implicitly_affected,
            )
        elif mv.type == "receipt":
            _apply_receipt_amendment(
                mv=mv,
                op=op,
                batches_map=batches_map,
                movements_map=movements_map,
                new_date=new_date,
                new_doc=new_doc,
                new_loc_id=new_loc_id,
                new_qty=new_qty,
            )
        else:
            movements_map[mv.id] = MovementSnapshot(
                id=mv.id,
                operation_date=new_date,
                created_at=mv.created_at,
                item_id=mv.item_id,
                location_id=new_loc_id,
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
                allocations=mv.allocations,
            )

    return (
        tuple(batches_map.values()),
        tuple(movements_map.values()),
        directly_affected,
        implicitly_affected,
    )
