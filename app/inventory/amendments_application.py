"""Атомарное подтверждение наборов складских исправлений и аудит версий."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.amendment_schemas import OperationItem
from app.core.timezone import now_in_moscow, today_in_moscow
from app.inventory.amendments_domain import AmendmentOperation
from app.inventory.amendments_parser import parse_operation_item
from app.inventory.amendments_service import simulate_amendment_set
from app.inventory.amendments_state import load_amendment_state
from app.inventory.exceptions import (
    AmendmentValidationError,
    EntityNotFoundError,
    StalePreviewError,
)
from app.inventory.versions import build_movement_snapshot
from app.models.amendments import AmendmentSet, MovementVersion
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder


def recalculate_purchase_orders(
    session: Session,
    locked_orders: Sequence[PurchaseOrder],
    as_of: date,
) -> None:
    """Пересчитывает принятую и ожидаемую части заказов по активным приходам в БД."""
    for po in locked_orders:
        stmt = select(func.coalesce(func.sum(Movement.quantity), Decimal("0.000"))).where(
            Movement.purchase_order_id == po.id,
            Movement.status == "active",
            Movement.type == "receipt",
        )
        total_received = Decimal(str(session.execute(stmt).scalar_one()))
        pending = po.expected_qty - total_received

        if pending < Decimal("0.000"):
            raise AmendmentValidationError(
                f"Принятое количество {total_received} превышает "
                f"ожидаемый объем заказа {po.expected_qty}",
                code="EXCESS_ORDER_RECEIPT",
                details={
                    "purchase_order_id": po.id,
                    "expected_qty": str(po.expected_qty),
                    "received_qty": str(total_received),
                },
            )

        po.received_qty = total_received
        po.pending_qty = pending

        if total_received >= po.expected_qty:
            po.status = "received"
        elif total_received > Decimal("0.000"):
            po.status = "delayed" if po.expected_date < as_of else "partially_received"
        else:
            po.status = "delayed" if po.expected_date < as_of else "pending"


def confirm_amendment_set(
    session: Session,
    preview_id: str,
    version_signature: str,
    reason: str,
    *,
    as_of: date | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Выполняет атомарное подтверждение предварительного просмотра с защитой от гонок."""
    stmt = select(AmendmentSet).where(AmendmentSet.amendment_id == preview_id)
    amendment_set = session.execute(stmt).scalar_one_or_none()
    if not amendment_set:
        raise EntityNotFoundError("AmendmentSet", preview_id)

    if amendment_set.status == "applied":
        raise StalePreviewError(
            "Набор исправлений уже применён ранее",
            code="stale_preview",
        )
    if amendment_set.status != "preview":
        raise StalePreviewError(
            f"Недопустимый статус набора исправлений: {amendment_set.status}",
            code="stale_preview",
        )
    if amendment_set.reason != reason.strip():
        raise StalePreviewError(
            "Причина подтверждения не совпадает с причиной предварительного просмотра",
            code="stale_preview",
        )
    if amendment_set.version_signature != version_signature:
        raise StalePreviewError(
            "Подпись версии предварительного просмотра не совпадает с переданной",
            code="stale_preview",
        )

    # Восстанавливаем операции из сохранённых строк
    operations: list[AmendmentOperation] = []
    for entry in sorted(amendment_set.entries, key=lambda e: e.id):
        op_item = OperationItem(
            movement_id=entry.movement_id,
            action=entry.action,  # type: ignore[arg-type]
            expected_version=entry.expected_version,
            fields=entry.details,
        )
        operations.append(parse_operation_item(op_item))

    # Блокируем пары и заказы, перечитываем актуальное состояние
    state = load_amendment_state(session, operations)

    if state.version_signature != version_signature:
        raise StalePreviewError(
            "Состояние склада изменилось с момента предварительного просмотра",
            code="stale_preview",
        )

    # Проверяем expected_version каждого движения
    m_map = {m.id: m for m in state.movements if m.id is not None}
    for op in operations:
        m = m_map.get(op.movement_id)
        if not m or m.current_version != op.expected_version:
            raise StalePreviewError(
                f"Версия движения {op.movement_id} изменилась",
                code="stale_preview",
            )

    calc_date = as_of or today_in_moscow()
    sim_result = simulate_amendment_set(
        batches=state.batch_snapshots,
        movements=state.movement_snapshots,
        operations=operations,
        today=calc_date,
        sku_by_item_id=state.sku_by_item_id,
        code_by_location_id=state.code_by_location_id,
        location_resolver=state.location_resolver,
    )

    if not sim_result.can_apply:
        first_blocker = sim_result.blockers[0]
        raise AmendmentValidationError(
            message=f"Нарушение зависимостей: {first_blocker.message}",
            code="dependency_violation",
            details={"blockers": [b.to_dict() for b in sim_result.blockers]},
        )

    # Применяем спроектированные изменения партий
    for p_b in sim_result.projected_batches:
        db_b = session.get(Batch, p_b.id)
        if db_b:
            db_b.location_id = p_b.location_id
            db_b.receipt_date = p_b.receipt_date
            db_b.receipt_doc_number = p_b.receipt_doc_number

    # Применяем спроектированные изменения движений и распределений
    op_by_mid = {op.movement_id: op for op in operations}
    for p_m in sim_result.projected_movements:
        if p_m.id is None:
            continue
        db_m = session.get(Movement, p_m.id)
        if not db_m:
            continue

        db_m.status = p_m.status
        db_m.quantity = p_m.quantity
        db_m.operation_date = p_m.operation_date
        db_m.doc_number = p_m.doc_number
        db_m.location_id = p_m.location_id
        db_m.batch_id = p_m.batch_id

        alloc_map = {a.id: a for a in (db_m.allocations or []) if a.id is not None}
        for p_a in p_m.allocations:
            if p_a.id in alloc_map:
                db_a = alloc_map[p_a.id]
                db_a.quantity = p_a.quantity
                db_a.batch_id = p_a.batch_id
                db_a.unit_price = p_a.unit_price

    session.flush()

    # Пересчитываем связанные заказы поставщикам
    recalculate_purchase_orders(session, state.purchase_orders, as_of=calc_date)

    # Записываем версии аудита для всех затронутых движений
    applied_movements: list[dict[str, Any]] = []
    all_affected = set(sim_result.affected_operations)
    for m_id in sorted(all_affected):
        db_m = session.get(Movement, m_id)
        if not db_m:
            continue

        action = op_by_mid[m_id].action if m_id in op_by_mid else "update"
        db_m.current_version += 1
        snapshot = build_movement_snapshot(db_m)

        version = MovementVersion(
            movement_id=db_m.id,
            version_num=db_m.current_version,
            action=action,
            reason=reason.strip(),
            snapshot=snapshot,
        )
        session.add(version)
        applied_movements.append(
            {
                "movement_id": db_m.id,
                "version": db_m.current_version,
                "action": action,
            }
        )

    amendment_set.status = "applied"
    amendment_set.applied_at = now_in_moscow()
    session.commit()

    return amendment_set.amendment_id, applied_movements
