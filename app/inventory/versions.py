"""Сервисная логика снимков и версий складских движений."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.inventory.exceptions import EntityNotFoundError
from app.models.amendments import MovementVersion
from app.models.inventory import Movement, MovementAllocation


def build_movement_snapshot(
    movement: Movement,
    allocations: Sequence[MovementAllocation] | None = None,
) -> dict[str, Any]:
    """Формирует неизменяемый снимок существенных полей движения и его строк."""
    alloc_list = allocations if allocations is not None else (movement.allocations or [])
    sorted_allocs = sorted(alloc_list, key=lambda a: (a.id or 0, a.batch_id))

    return {
        "id": movement.id,
        "operation_date": (
            movement.operation_date.isoformat()
            if hasattr(movement.operation_date, "isoformat")
            else str(movement.operation_date)
        ),
        "type": movement.type,
        "quantity": f"{Decimal(str(movement.quantity)):.3f}",
        "doc_number": movement.doc_number,
        "status": movement.status,
        "item_id": movement.item_id,
        "location_id": movement.location_id,
        "batch_id": movement.batch_id,
        "reason": movement.reason,
        "parent_movement_id": movement.parent_movement_id,
        "parent_allocation_id": movement.parent_allocation_id,
        "purchase_order_id": movement.purchase_order_id,
        "supplier_id": movement.supplier_id,
        "allocations": [
            {
                "id": a.id,
                "batch_id": a.batch_id,
                "quantity": f"{Decimal(str(a.quantity)):.3f}",
                "unit_price": f"{Decimal(str(a.unit_price)):.2f}",
            }
            for a in sorted_allocs
        ],
    }


def calculate_changes(
    prev_snapshot: dict[str, Any] | None,
    curr_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Вычисляет различия между двумя последовательными снимками версий."""
    if not prev_snapshot:
        return {}

    changes: dict[str, Any] = {}
    all_keys = sorted(set(prev_snapshot.keys()) | set(curr_snapshot.keys()))
    for key in all_keys:
        if key in ("id", "item_id", "location_id", "type"):
            continue
        prev_val = prev_snapshot.get(key)
        curr_val = curr_snapshot.get(key)
        if prev_val != curr_val:
            changes[key] = {"old": prev_val, "new": curr_val}
    return changes


def create_initial_movement_version(
    session: Session,
    movement: Movement,
    allocations: Sequence[MovementAllocation] | None = None,
) -> MovementVersion:
    """Создаёт снимок версии 1 при первичной регистрации складского движения."""
    snapshot = build_movement_snapshot(movement, allocations=allocations)
    version = MovementVersion(
        movement_id=movement.id,
        version_num=1,
        action="create",
        reason="Первичный ввод",
        snapshot=snapshot,
    )
    session.add(version)
    session.flush()
    return version


def get_movement_history_data(
    session: Session,
    movement_id: int,
) -> tuple[Movement, list[dict[str, Any]]]:
    """Возвращает движение и подготовленный список версий с изменениями."""
    stmt = (
        select(Movement)
        .options(
            joinedload(Movement.allocations),
            joinedload(Movement.versions),
        )
        .where(Movement.id == movement_id)
    )
    movement = session.execute(stmt).unique().scalar_one_or_none()
    if not movement:
        raise EntityNotFoundError("Movement", movement_id)

    sorted_versions = sorted(movement.versions or [], key=lambda v: v.version_num)

    if not sorted_versions:
        curr_snap = build_movement_snapshot(movement)
        return movement, [
            {
                "version_num": 1,
                "created_at": movement.created_at,
                "action": "create",
                "reason": "Первичный ввод",
                "snapshot": curr_snap,
                "changes": {},
            }
        ]

    version_items: list[dict[str, Any]] = []
    for i, v in enumerate(sorted_versions):
        prev_snap = sorted_versions[i - 1].snapshot if i > 0 else None
        changes = calculate_changes(prev_snap, v.snapshot)
        version_items.append(
            {
                "version_num": v.version_num,
                "created_at": v.created_at,
                "action": v.action,
                "reason": v.reason,
                "snapshot": v.snapshot,
                "changes": changes,
            }
        )

    return movement, version_items
