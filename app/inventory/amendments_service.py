"""Сервис симуляции и расчёта наборов исправлений склада."""

import uuid
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.timezone import today_in_moscow
from app.inventory.amendments_domain import (
    AmendmentOperation,
    SimulationResult,
    StockImpact,
)
from app.inventory.amendments_simulation import apply_amendments_to_snapshots
from app.inventory.amendments_state import load_amendment_state
from app.inventory.amendments_validation import validate_projected_history
from app.inventory.calculator import calculate_batch_stocks
from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.inventory.exceptions import AmendmentValidationError
from app.models.amendments import AmendmentEntry, AmendmentSet

_ZERO = Decimal("0.000")


def create_amendment_preview(
    session: Session,
    reason: str,
    operations: Sequence[AmendmentOperation],
) -> tuple[str, str, SimulationResult]:
    """Строит предварительный просмотр набора исправлений и сохраняет его в БД."""
    state = load_amendment_state(session, operations)
    sim_result = simulate_amendment_set(
        batches=state.batch_snapshots,
        movements=state.movement_snapshots,
        operations=operations,
        sku_by_item_id=state.sku_by_item_id,
        code_by_location_id=state.code_by_location_id,
        location_resolver=state.location_resolver,
    )

    preview_id = str(uuid.uuid4())
    amendment_set = AmendmentSet(
        amendment_id=preview_id,
        reason=reason,
        status="preview",
        version_signature=state.version_signature,
        preview_data={
            "can_apply": sim_result.can_apply,
            "stock_impact": [s.to_dict() for s in sim_result.stock_impact],
            "affected_operations": list(sim_result.affected_operations),
            "blockers": [b.to_dict() for b in sim_result.blockers],
        },
    )
    session.add(amendment_set)
    session.flush()

    for op in operations:
        entry = AmendmentEntry(
            amendment_set_id=amendment_set.id,
            movement_id=op.movement_id,
            action=op.action,
            expected_version=op.expected_version,
            details=op.raw_fields,
        )
        session.add(entry)
    session.commit()

    return preview_id, state.version_signature, sim_result


def simulate_amendment_set(
    batches: Sequence[BatchSnapshot],
    movements: Sequence[MovementSnapshot],
    operations: Sequence[AmendmentOperation],
    *,
    today: date | None = None,
    sku_by_item_id: dict[int, str] | None = None,
    code_by_location_id: dict[int, str] | None = None,
    location_resolver: Callable[[str], int | None] | None = None,
) -> SimulationResult:
    """Выполняет чистую симуляцию набора исправлений на снимках данных склада."""
    if not operations:
        raise AmendmentValidationError(
            "Список операций не может быть пустым", code="EMPTY_OPERATIONS"
        )

    as_of = today or today_in_moscow()

    proj_batches, proj_movements, directly_affected, implicitly_affected = (
        apply_amendments_to_snapshots(
            batches=batches,
            movements=movements,
            operations=operations,
            location_resolver=location_resolver,
        )
    )

    blockers = validate_projected_history(
        projected_batches=proj_batches,
        projected_movements=proj_movements,
        original_movements=movements,
        operations=operations,
        today=as_of,
    )

    # Определяем затронутые партии для расчёта изменения остатков
    touched_batch_ids: set[int] = set()
    orig_m_map = {m.id: m for m in movements if m.id is not None}
    proj_m_map = {m.id: m for m in proj_movements if m.id is not None}

    all_affected_m_ids = directly_affected | implicitly_affected
    for m_id in all_affected_m_ids:
        for m_map in (orig_m_map, proj_m_map):
            if m_id in m_map:
                m = m_map[m_id]
                if m.batch_id is not None:
                    touched_batch_ids.add(m.batch_id)
                for a in m.allocations:
                    touched_batch_ids.add(a.batch_id)

    orig_b_map = {b.id: b for b in batches}
    proj_b_map = {b.id: b for b in proj_batches}
    for b_id, p_b in proj_b_map.items():
        if b_id in orig_b_map:
            o_b = orig_b_map[b_id]
            if (
                o_b.location_id != p_b.location_id
                or o_b.receipt_date != p_b.receipt_date
                or o_b.receipt_doc_number != p_b.receipt_doc_number
            ):
                touched_batch_ids.add(b_id)

    for op in operations:
        if op.allocation_batch_change:
            touched_batch_ids.add(op.allocation_batch_change.new_batch_id)

    stocks_before = calculate_batch_stocks(batches, movements, as_of=as_of, include_zero=True)
    stocks_after = calculate_batch_stocks(
        proj_batches, proj_movements, as_of=as_of, include_zero=True
    )

    stock_impacts: list[StockImpact] = []
    for b_id in sorted(touched_batch_ids):
        b = proj_b_map.get(b_id) or orig_b_map.get(b_id)
        if not b:
            continue

        st_b = stocks_before.get(b_id)
        st_a = stocks_after.get(b_id)

        curr_before = st_b.current_quantity if st_b else _ZERO
        avail_before = st_b.available_quantity if st_b else _ZERO
        curr_after = st_a.current_quantity if st_a else _ZERO
        avail_after = st_a.available_quantity if st_a else _ZERO

        if curr_before != curr_after or avail_before != avail_after:
            sku = (sku_by_item_id or {}).get(b.item_id, f"ITEM-{b.item_id}")
            loc = (code_by_location_id or {}).get(b.location_id, f"LOC-{b.location_id}")
            stock_impacts.append(
                StockImpact(
                    sku=sku,
                    location=loc,
                    batch_id=b_id,
                    current_stock_before=curr_before,
                    current_stock_after=curr_after,
                    available_stock_before=avail_before,
                    available_stock_after=avail_after,
                )
            )

    stock_impacts.sort(key=lambda s: (s.sku, s.location, s.batch_id))
    affected_operations = tuple(sorted(all_affected_m_ids))

    return SimulationResult(
        can_apply=len(blockers) == 0,
        stock_impact=tuple(stock_impacts),
        affected_operations=affected_operations,
        blockers=tuple(blockers),
        projected_movements=proj_movements,
        projected_batches=proj_batches,
    )
