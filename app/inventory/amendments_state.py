"""Загрузка данных и детерминированная блокировка для наборов складских исправлений."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.inventory.amendments_domain import AmendmentOperation
from app.inventory.amendments_signature import compute_state_signature
from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.inventory.exceptions import EntityNotFoundError
from app.inventory.repository import (
    acquire_stock_lock,
    batch_to_snapshot,
    get_batches,
    get_movements_with_allocations,
    movement_to_snapshot,
)
from app.models.catalog import Item, Location
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder


@dataclass(frozen=True)
class LoadedAmendmentState:
    """Полное заблокированное состояние затронутых пар и заказов."""

    pairs: tuple[tuple[int, int], ...]
    movements: tuple[Movement, ...]
    batches: tuple[Batch, ...]
    purchase_orders: tuple[PurchaseOrder, ...]
    purchase_order_quantities: dict[int, tuple[Decimal, Decimal]]
    movement_snapshots: tuple[MovementSnapshot, ...]
    batch_snapshots: tuple[BatchSnapshot, ...]
    sku_by_item_id: dict[int, str]
    code_by_location_id: dict[int, str]
    location_resolver: Callable[[str], int | None]
    version_signature: str
    active_location_docs: tuple[tuple[int, int, str], ...] = ()


def find_affected_pairs_and_orders(
    session: Session,
    operations: Sequence[AmendmentOperation],
) -> tuple[list[tuple[int, int]], list[int]]:
    """Находит все затронутые пары (item_id, location_id) и заказы поставщику."""
    pairs: set[tuple[int, int]] = set()
    po_ids: set[int] = set()

    for op in operations:
        movement = session.get(Movement, op.movement_id)
        if not movement:
            raise EntityNotFoundError("Movement", op.movement_id)

        pairs.add((movement.item_id, movement.location_id))
        if movement.purchase_order_id is not None:
            po_ids.add(movement.purchase_order_id)

        target_loc_id = op.location_id
        loc_code = op.location_code or op.raw_fields.get("location")
        if target_loc_id is None and loc_code:
            loc = session.execute(
                select(Location).where(Location.code == str(loc_code))
            ).scalar_one_or_none()
            if not loc:
                raise EntityNotFoundError("Location", loc_code)
            target_loc_id = loc.id

        if target_loc_id is not None:
            pairs.add((movement.item_id, target_loc_id))

        if op.allocation_batch_change:
            b = session.get(Batch, op.allocation_batch_change.new_batch_id)
            if not b:
                raise EntityNotFoundError("Batch", op.allocation_batch_change.new_batch_id)
            pairs.add((b.item_id, b.location_id))

    sorted_pairs = sorted(pairs, key=lambda p: (p[0], p[1]))
    sorted_po_ids = sorted(po_ids)
    return sorted_pairs, sorted_po_ids


def acquire_amendment_locks(
    session: Session,
    pairs: Sequence[tuple[int, int]],
    po_ids: Sequence[int] | None = None,
) -> list[PurchaseOrder]:
    """Блокирует пары (item_id, location_id) и заказы в устойчивом детерминированном порядке."""
    sorted_pairs = sorted(set(pairs), key=lambda p: (p[0], p[1]))
    for item_id, location_id in sorted_pairs:
        acquire_stock_lock(session, item_id, location_id)

    if po_ids:
        sorted_pos = sorted(set(po_ids))
        stmt = (
            select(PurchaseOrder)
            .where(PurchaseOrder.id.in_(sorted_pos))
            .order_by(PurchaseOrder.id.asc())
            .with_for_update()
        )
        return list(session.execute(stmt).scalars().all())
    return []


def load_amendment_state(
    session: Session,
    operations: Sequence[AmendmentOperation],
) -> LoadedAmendmentState:
    """Загружает данные, берёт блокировки в детерминированном порядке и считает подпись."""
    pairs, initial_po_ids = find_affected_pairs_and_orders(session, operations)
    acquire_amendment_locks(session, pairs, initial_po_ids)

    all_movements: list[Movement] = []
    all_batches: list[Batch] = []
    for item_id, location_id in pairs:
        all_movements.extend(get_movements_with_allocations(session, item_id, location_id))
        all_batches.extend(get_batches(session, item_id, location_id))

    seen_m: set[int] = set()
    unique_movements: list[Movement] = []
    for m in all_movements:
        if m.id is not None and m.id not in seen_m:
            seen_m.add(m.id)
            unique_movements.append(m)
    unique_movements.sort(key=lambda m: (m.operation_date, m.id or 0))

    seen_b: set[int] = set()
    unique_batches: list[Batch] = []
    for b in all_batches:
        if b.id is not None and b.id not in seen_b:
            seen_b.add(b.id)
            unique_batches.append(b)
    unique_batches.sort(key=lambda b: b.id or 0)

    all_po_ids = set(initial_po_ids)
    for m in unique_movements:
        if m.purchase_order_id is not None:
            all_po_ids.add(m.purchase_order_id)

    locked_pos: list[PurchaseOrder] = []
    if all_po_ids:
        stmt = (
            select(PurchaseOrder)
            .where(PurchaseOrder.id.in_(sorted(all_po_ids)))
            .order_by(PurchaseOrder.id.asc())
            .with_for_update()
        )
        locked_pos = list(session.execute(stmt).scalars().all())

    purchase_order_quantities: dict[int, tuple[Decimal, Decimal]] = {}
    for po in locked_pos:
        received_stmt = select(func.coalesce(func.sum(Movement.quantity), 0)).where(
            Movement.purchase_order_id == po.id,
            Movement.status == "active",
            Movement.type == "receipt",
        )
        received = Decimal(str(session.execute(received_stmt).scalar_one()))
        purchase_order_quantities[po.id] = (Decimal(str(po.expected_qty)), received)

    item_ids = {p[0] for p in pairs}
    location_ids = {p[1] for p in pairs}
    items = session.execute(select(Item).where(Item.id.in_(item_ids))).scalars().all()
    sku_by_item_id = {it.id: it.sku for it in items}

    locations = (
        session.execute(select(Location).where(Location.id.in_(location_ids))).scalars().all()
    )
    code_by_location_id = {loc.id: loc.code for loc in locations}
    code_to_id = {loc.code: loc.id for loc in locations}

    def location_resolver(code: str) -> int | None:
        if code in code_to_id:
            return code_to_id[code]
        loc = session.execute(select(Location).where(Location.code == code)).scalar_one_or_none()
        if loc:
            code_to_id[loc.code] = loc.id
            return loc.id
        return None

    movement_snapshots = [movement_to_snapshot(m) for m in unique_movements]
    batch_snapshots = [batch_to_snapshot(b) for b in unique_batches]

    signature = compute_state_signature(
        pairs=pairs,
        movements=unique_movements,
        batches=unique_batches,
        purchase_orders=locked_pos,
        operations=operations,
    )

    active_docs_stmt = select(Movement.id, Movement.location_id, Movement.doc_number).where(
        Movement.location_id.in_(location_ids),
        Movement.status == "active",
    )
    active_location_docs = tuple(
        (int(r[0]), int(r[1]), str(r[2]))
        for r in session.execute(active_docs_stmt).all()
        if r[0] is not None
    )

    return LoadedAmendmentState(
        pairs=tuple(pairs),
        movements=tuple(unique_movements),
        batches=tuple(unique_batches),
        purchase_orders=tuple(locked_pos),
        purchase_order_quantities=purchase_order_quantities,
        movement_snapshots=tuple(movement_snapshots),
        batch_snapshots=tuple(batch_snapshots),
        sku_by_item_id=sku_by_item_id,
        code_by_location_id=code_by_location_id,
        location_resolver=location_resolver,
        version_signature=signature,
        active_location_docs=active_location_docs,
    )
