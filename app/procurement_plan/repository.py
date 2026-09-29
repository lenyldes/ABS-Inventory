"""Репозиторий пакетной выборки согласованного снимка БД для плана закупок."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from app.api.plan_schemas import ExistingOrderSnapshotSchema
from app.inventory.repository import batch_to_snapshot, movement_to_snapshot
from app.models.catalog import Item, Location
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder, SupplierCondition
from app.procurement_plan.domain import PlanDatabaseSnapshot
from app.procurement_plan.snapshot_builder import assemble_plan_pairs

_ZERO_QTY = Decimal("0.000")


def set_repeatable_read_snapshot(session: Session) -> None:
    """Устанавливает уровень изоляции транзакции REPEATABLE READ для снимка БД."""
    if session.in_transaction():
        current_iso = None
        try:
            current_iso = session.execute(text("SHOW transaction_isolation")).scalar()
        except Exception:
            pass
        if current_iso and str(current_iso).lower() == "repeatable read":
            return
        raise RuntimeError(
            "Невозможно установить уровень изоляции REPEATABLE READ: "
            "в сессии уже начата транзакция с несовместимым уровнем изоляции."
        )
    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})


def load_catalog_pairs(
    session: Session,
    location_code: str | None = None,
    category: str | None = None,
) -> list[tuple[Item, Location]]:
    """Выбирает пары «товар + объект» с устойчивой сортировкой: объект, категория, SKU."""
    loc_stmt = select(Location).order_by(Location.code.asc())
    if location_code is not None:
        loc_stmt = loc_stmt.where(Location.code == location_code)
    locations = list(session.execute(loc_stmt).scalars().all())

    item_stmt = select(Item).order_by(Item.category.asc(), Item.sku.asc())
    if category is not None:
        item_stmt = item_stmt.where(Item.category == category)
    items = list(session.execute(item_stmt).scalars().all())

    pairs: list[tuple[Item, Location]] = []
    for loc in locations:
        for it in items:
            pairs.append((it, loc))
    return pairs


def load_active_orders_for_pair(
    session: Session,
    item_id: int,
    location_id: int,
    sku: str,
    location_code: str,
) -> tuple[ExistingOrderSnapshotSchema, ...]:
    """Загружает действующие ожидаемые заказы для одной пары (для тестов и точечных выборок)."""
    stmt = (
        select(PurchaseOrder)
        .options(joinedload(PurchaseOrder.supplier))
        .where(
            PurchaseOrder.item_id == item_id,
            PurchaseOrder.location_id == location_id,
            PurchaseOrder.status != "cancelled",
            PurchaseOrder.pending_qty > _ZERO_QTY,
        )
        .order_by(PurchaseOrder.expected_date.asc(), PurchaseOrder.id.asc())
    )
    orders = list(session.execute(stmt).scalars().all())
    result: list[ExistingOrderSnapshotSchema] = []
    for order in orders:
        supplier_str_id = order.supplier.supplier_id if order.supplier else None
        supplier_name = order.supplier.name if order.supplier else None
        result.append(
            ExistingOrderSnapshotSchema(
                order_id=order.id,
                doc_number=order.doc_number,
                sku=sku,
                location=location_code,
                expected_date=order.expected_date,
                pending_qty=order.pending_qty,
                unit_price=order.unit_price,
                supplier_id=supplier_str_id,
                supplier_name=supplier_name,
            )
        )
    return tuple(result)


def load_plan_database_snapshot(
    session: Session,
    as_of: date,
    location_code: str | None = None,
    category: str | None = None,
) -> PlanDatabaseSnapshot:
    """Формирует согласованный снимок БД через пакетные выборки O(1)."""
    catalog_pairs = load_catalog_pairs(session, location_code, category)
    if not catalog_pairs:
        return PlanDatabaseSnapshot(as_of=as_of, pairs=(), existing_orders=())

    item_ids = list(dict.fromkeys(it.id for it, _ in catalog_pairs))
    location_ids = list(dict.fromkeys(loc.id for _, loc in catalog_pairs))

    # 1. Загрузка условий основных поставщиков пакетно для всех отобранных товаров
    cond_stmt = (
        select(SupplierCondition)
        .options(joinedload(SupplierCondition.supplier))
        .where(
            SupplierCondition.item_id.in_(item_ids),
            SupplierCondition.is_primary.is_(True),
        )
    )
    conditions = session.execute(cond_stmt).scalars().all()
    conditions_by_item: dict[int, SupplierCondition] = {c.item_id: c for c in conditions}

    # 2. Загрузка цен последних поступлений пакетно для всех отобранных товаров
    receipt_stmt = (
        select(Movement)
        .options(joinedload(Movement.batch), joinedload(Movement.purchase_order))
        .where(
            Movement.item_id.in_(item_ids),
            Movement.type == "receipt",
            Movement.status == "active",
            Movement.operation_date <= as_of,
        )
        .order_by(
            Movement.item_id.asc(),
            Movement.operation_date.desc(),
            Movement.id.desc(),
        )
    )
    receipt_movements = session.execute(receipt_stmt).unique().scalars().all()

    receipt_prices: dict[int, Decimal] = {}
    for mv in receipt_movements:
        it_id = mv.item_id
        if it_id in receipt_prices:
            continue
        cond = conditions_by_item.get(it_id)
        if cond is None:
            continue
        sup_id = mv.purchase_order.supplier_id if mv.purchase_order else mv.supplier_id
        if sup_id == cond.supplier_id and mv.batch and mv.batch.unit_price is not None:
            receipt_prices[it_id] = mv.batch.unit_price

    # 3. Загрузка действующих заказов пакетно для всех отобранных товаров и объектов
    orders_stmt = (
        select(PurchaseOrder)
        .options(joinedload(PurchaseOrder.supplier))
        .where(
            PurchaseOrder.item_id.in_(item_ids),
            PurchaseOrder.location_id.in_(location_ids),
            PurchaseOrder.status != "cancelled",
            PurchaseOrder.pending_qty > _ZERO_QTY,
        )
        .order_by(PurchaseOrder.expected_date.asc(), PurchaseOrder.id.asc())
    )
    all_pos = session.execute(orders_stmt).scalars().all()
    orders_by_pair: dict[tuple[int, int], list[PurchaseOrder]] = defaultdict(list)
    for po in all_pos:
        orders_by_pair[(po.item_id, po.location_id)].append(po)

    # 4. Загрузка партий пакетно для всех отобранных пар
    batch_stmt = (
        select(Batch)
        .where(
            Batch.item_id.in_(item_ids),
            Batch.location_id.in_(location_ids),
        )
        .order_by(Batch.id.asc())
    )
    all_batches = session.execute(batch_stmt).scalars().all()
    batches_by_pair: dict[tuple[int, int], list] = defaultdict(list)
    for b in all_batches:
        batches_by_pair[(b.item_id, b.location_id)].append(batch_to_snapshot(b))

    # 5. Загрузка движений с распределениями пакетно для всех отобранных пар
    mv_stmt = (
        select(Movement)
        .options(joinedload(Movement.allocations))
        .where(
            Movement.item_id.in_(item_ids),
            Movement.location_id.in_(location_ids),
        )
        .order_by(Movement.operation_date.asc(), Movement.id.asc())
    )
    all_mvs = session.execute(mv_stmt).unique().scalars().all()
    movements_by_pair: dict[tuple[int, int], list] = defaultdict(list)
    for m in all_mvs:
        movements_by_pair[(m.item_id, m.location_id)].append(movement_to_snapshot(m))

    # Сборка снимков пар в детерминированном порядке через построитель
    pairs_data = assemble_plan_pairs(
        catalog_pairs=catalog_pairs,
        conditions_by_item=conditions_by_item,
        receipt_prices=receipt_prices,
        orders_by_pair=orders_by_pair,
        batches_by_pair=batches_by_pair,
        movements_by_pair=movements_by_pair,
        as_of=as_of,
    )

    all_existing_orders = tuple(order for pair in pairs_data for order in pair.active_orders)

    return PlanDatabaseSnapshot(
        as_of=as_of,
        pairs=tuple(pairs_data),
        existing_orders=all_existing_orders,
    )
