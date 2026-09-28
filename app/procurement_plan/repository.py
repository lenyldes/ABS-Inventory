"""Репозиторий выборки согласованного снимка БД для плана закупок."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from app.api.plan_schemas import ExistingOrderSnapshotSchema
from app.forecasting.procurement_repository import load_procurement_context
from app.inventory.common_validation import load_history
from app.models.catalog import Item, Location
from app.models.procurement import PurchaseOrder
from app.procurement_plan.domain import PlanDatabaseSnapshot, PlanItemLocationPair

_ZERO_QTY = Decimal("0.000")


def set_repeatable_read_snapshot(session: Session) -> None:
    """Устанавливает уровень изоляции транзакции REPEATABLE READ для снимка БД."""
    if session.in_transaction():
        current_iso = session.execute(text("SHOW transaction_isolation")).scalar()
        if current_iso and str(current_iso).lower() == "repeatable read":
            return
        session.rollback()
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
    """Загружает действующие ожидаемые заказы для пары без отменённых и полностью полученных."""
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
    """Формирует согласованный снимок БД в REPEATABLE READ: пары, условия, FEFO и заказы."""
    set_repeatable_read_snapshot(session)

    catalog_pairs = load_catalog_pairs(session, location_code, category)
    pairs_data: list[PlanItemLocationPair] = []

    for item, location in catalog_pairs:
        procurement_context = load_procurement_context(session, item.id, location.id, as_of)
        _, _, b_snaps, m_snaps = load_history(session, item.id, location.id)
        pair_orders = load_active_orders_for_pair(
            session=session,
            item_id=item.id,
            location_id=location.id,
            sku=item.sku,
            location_code=location.code,
        )
        pairs_data.append(
            PlanItemLocationPair(
                item=item,
                location=location,
                batches=tuple(b_snaps),
                movements=tuple(m_snaps),
                procurement_context=procurement_context,
                active_orders=pair_orders,
            )
        )

    all_existing_orders = tuple(order for pair in pairs_data for order in pair.active_orders)

    return PlanDatabaseSnapshot(
        as_of=as_of,
        pairs=tuple(pairs_data),
        existing_orders=all_existing_orders,
    )
