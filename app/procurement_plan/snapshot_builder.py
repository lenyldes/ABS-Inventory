"""Построитель доменных структур согласованного снимка БД для плана закупок."""

from datetime import date
from decimal import Decimal

from app.api.plan_schemas import ExistingOrderSnapshotSchema
from app.forecasting.domain import IncomingOrderSnapshot, ProcurementContext
from app.models.catalog import Item, Location
from app.models.procurement import PurchaseOrder, SupplierCondition
from app.procurement_plan.domain import PlanItemLocationPair


def build_pair_procurement_context(
    item: Item,
    cond: SupplierCondition | None,
    receipt_prices: dict[int, Decimal],
    pair_pos: list[PurchaseOrder],
    as_of: date,
) -> ProcurementContext:
    """Формирует контекст закупок (условия, цены, входящие заказы) для пары."""
    supplier_str_id = None
    supplier_name = None
    lead_time_days = None
    package_size = None
    min_order_qty = None
    unit_price = None
    price_source = None

    if cond is not None:
        if cond.supplier is not None:
            supplier_str_id = cond.supplier.supplier_id
            supplier_name = cond.supplier.name
        lead_time_days = cond.lead_time_days
        package_size = cond.package_size
        min_order_qty = cond.min_order_qty

        if item.id in receipt_prices:
            unit_price = receipt_prices[item.id]
            price_source = "receipt"
        elif cond.estimated_price is not None:
            unit_price = cond.estimated_price
            price_source = "estimated"

    pending_snapshots: list[IncomingOrderSnapshot] = []
    delayed_snapshots: list[IncomingOrderSnapshot] = []

    for po in pair_pos:
        snap = IncomingOrderSnapshot(
            order_id=po.id,
            doc_number=po.doc_number,
            expected_date=po.expected_date,
            pending_qty=po.pending_qty,
            unit_price=po.unit_price,
        )
        if po.expected_date <= as_of:
            delayed_snapshots.append(snap)
        else:
            pending_snapshots.append(snap)

    return ProcurementContext(
        supplier_id=supplier_str_id,
        supplier_name=supplier_name,
        lead_time_days=lead_time_days,
        package_size=package_size,
        min_order_qty=min_order_qty,
        unit_price=unit_price,
        price_source=price_source,
        pending_orders=tuple(pending_snapshots),
        delayed_orders=tuple(delayed_snapshots),
    )


def build_pair_existing_orders(
    pair_pos: list[PurchaseOrder],
    sku: str,
    location_code: str,
) -> tuple[ExistingOrderSnapshotSchema, ...]:
    """Формирует список снимков существующих заказов для контракта API."""
    schemas: list[ExistingOrderSnapshotSchema] = []
    for po in pair_pos:
        sup_str_id = po.supplier.supplier_id if po.supplier else None
        sup_nm = po.supplier.name if po.supplier else None
        schemas.append(
            ExistingOrderSnapshotSchema(
                order_id=po.id,
                doc_number=po.doc_number,
                sku=sku,
                location=location_code,
                expected_date=po.expected_date,
                pending_qty=po.pending_qty,
                unit_price=po.unit_price,
                supplier_id=sup_str_id,
                supplier_name=sup_nm,
            )
        )
    return tuple(schemas)


def assemble_plan_pairs(
    catalog_pairs: list[tuple[Item, Location]],
    conditions_by_item: dict[int, SupplierCondition],
    receipt_prices: dict[int, Decimal],
    orders_by_pair: dict[tuple[int, int], list[PurchaseOrder]],
    batches_by_pair: dict[tuple[int, int], list],
    movements_by_pair: dict[tuple[int, int], list],
    as_of: date,
) -> list[PlanItemLocationPair]:
    """Собирает доменные снимки пар «товар + объект» в заданном порядке."""
    pairs_data: list[PlanItemLocationPair] = []

    for item, location in catalog_pairs:
        cond = conditions_by_item.get(item.id)
        pair_pos = orders_by_pair.get((item.id, location.id), [])

        ctx = build_pair_procurement_context(
            item=item,
            cond=cond,
            receipt_prices=receipt_prices,
            pair_pos=pair_pos,
            as_of=as_of,
        )
        orders = build_pair_existing_orders(
            pair_pos=pair_pos,
            sku=item.sku,
            location_code=location.code,
        )

        pairs_data.append(
            PlanItemLocationPair(
                item=item,
                location=location,
                batches=tuple(batches_by_pair.get((item.id, location.id), ())),
                movements=tuple(movements_by_pair.get((item.id, location.id), ())),
                procurement_context=ctx,
                active_orders=orders,
            )
        )

    return pairs_data
