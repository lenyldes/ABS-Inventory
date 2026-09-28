"""Сервисная логика операций списания (writeoff), возврата (return) и корректировки (correction)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.inventory.calculator import calculate_stock_balance
from app.inventory.common_validation import (
    MovementExecutionResult,
    load_history,
    validate_common_rules,
)
from app.inventory.exceptions import (
    EntityNotFoundError,
    ExcessReturnError,
    InvalidMovementError,
)
from app.inventory.history import validate_history_sufficiency
from app.inventory.repository import (
    create_movement,
    get_allocation_by_id,
    get_movement_by_id,
    get_movements_with_allocations,
    movement_to_snapshot,
)
from app.models.catalog import Item, Location

_ZERO = Decimal("0.000")


def register_writeoff(
    session: Session,
    *,
    item: Item,
    location: Location,
    operation_date: date,
    quantity: Decimal,
    doc_number: str,
    batch_id: int,
    reason: str,
) -> MovementExecutionResult:
    """Регистрирует списание (writeoff) из указанной партии."""
    if not reason or not reason.strip():
        raise InvalidMovementError("Для списания обязательна причина", code="MISSING_REASON")

    validate_common_rules(session, item, location, operation_date, quantity, doc_number)
    batches, _, b_snaps, m_snaps = load_history(session, item.id, location.id)

    target_batch = next((b for b in batches if b.id == batch_id), None)
    if not target_batch:
        raise EntityNotFoundError("Batch", batch_id)

    mv = create_movement(
        session,
        operation_date=operation_date,
        item_id=item.id,
        location_id=location.id,
        type="writeoff",
        quantity=quantity,
        doc_number=doc_number,
        batch_id=batch_id,
        reason=reason,
    )

    new_snap = movement_to_snapshot(mv)
    validate_history_sufficiency(b_snaps, m_snaps, new_movement=new_snap)

    all_m = m_snaps + [new_snap]
    balance = calculate_stock_balance(b_snaps, all_m, as_of=date.today())
    return MovementExecutionResult(
        movement=mv,
        current_stock=balance.current_stock,
        available_stock=balance.available_stock,
    )


def register_return(
    session: Session,
    *,
    item: Item,
    location: Location,
    operation_date: date,
    quantity: Decimal,
    doc_number: str,
    parent_movement_id: int,
    parent_allocation_id: int,
    reason: str | None = None,
) -> MovementExecutionResult:
    """Регистрирует возврат неиспользованного материала по строке расхода."""
    validate_common_rules(session, item, location, operation_date, quantity, doc_number)

    parent_mv = get_movement_by_id(session, parent_movement_id)
    if not parent_mv or parent_mv.type != "consume":
        raise EntityNotFoundError("ParentConsumeMovement", parent_movement_id)

    parent_alloc = get_allocation_by_id(session, parent_allocation_id)
    if not parent_alloc or parent_alloc.movement_id != parent_movement_id:
        raise EntityNotFoundError("ParentAllocation", parent_allocation_id)

    if parent_mv.item_id != item.id or parent_mv.location_id != location.id:
        raise InvalidMovementError(
            "Исходный расход относится к другому товару или объекту",
            code="PARENT_MISMATCH",
        )

    if operation_date < parent_mv.operation_date:
        raise InvalidMovementError(
            f"Дата возврата {operation_date.isoformat()} не может быть "
            f"раньше расхода {parent_mv.operation_date.isoformat()}",
            code="INVALID_RETURN_DATE",
        )

    existing_returns = [
        m.quantity
        for m in get_movements_with_allocations(session, item.id, location.id)
        if m.type == "return"
        and m.parent_allocation_id == parent_allocation_id
        and m.status == "active"
    ]
    already_returned = sum(existing_returns, _ZERO)
    max_allowed = parent_alloc.quantity - already_returned
    if quantity > max_allowed:
        raise ExcessReturnError(
            requested_return=quantity,
            max_allowed_return=max_allowed,
            parent_allocation_id=parent_allocation_id,
        )

    _, _, b_snaps, m_snaps = load_history(session, item.id, location.id)

    mv = create_movement(
        session,
        operation_date=operation_date,
        item_id=item.id,
        location_id=location.id,
        type="return",
        quantity=quantity,
        doc_number=doc_number,
        batch_id=parent_alloc.batch_id,
        parent_movement_id=parent_movement_id,
        parent_allocation_id=parent_allocation_id,
        reason=reason,
    )

    new_snap = movement_to_snapshot(mv)
    validate_history_sufficiency(b_snaps, m_snaps, new_movement=new_snap)

    all_m = m_snaps + [new_snap]
    balance = calculate_stock_balance(b_snaps, all_m, as_of=date.today())
    return MovementExecutionResult(
        movement=mv,
        current_stock=balance.current_stock,
        available_stock=balance.available_stock,
    )


def register_correction(
    session: Session,
    *,
    item: Item,
    location: Location,
    operation_date: date,
    quantity: Decimal,
    doc_number: str,
    batch_id: int,
    reason: str,
) -> MovementExecutionResult:
    """Регистрирует инвентаризационную корректировку (со знаком и причиной)."""
    if not reason or not reason.strip():
        raise InvalidMovementError("Для корректировки обязательна причина", code="MISSING_REASON")

    validate_common_rules(
        session,
        item,
        location,
        operation_date,
        quantity,
        doc_number,
        allow_negative=True,
    )
    batches, _, b_snaps, m_snaps = load_history(session, item.id, location.id)

    target_batch = next((b for b in batches if b.id == batch_id), None)
    if not target_batch:
        raise EntityNotFoundError("Batch", batch_id)

    mv = create_movement(
        session,
        operation_date=operation_date,
        item_id=item.id,
        location_id=location.id,
        type="correction",
        quantity=quantity,
        doc_number=doc_number,
        batch_id=batch_id,
        reason=reason,
    )

    new_snap = movement_to_snapshot(mv)
    validate_history_sufficiency(b_snaps, m_snaps, new_movement=new_snap)

    all_m = m_snaps + [new_snap]
    balance = calculate_stock_balance(b_snaps, all_m, as_of=date.today())
    return MovementExecutionResult(
        movement=mv,
        current_stock=balance.current_stock,
        available_stock=balance.available_stock,
    )
