"""Репозиторий закупочных условий, цен и ожидаемых поставок для прогнозирования."""

from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.forecasting.domain import IncomingOrderSnapshot, ProcurementContext
from app.inventory.common_validation import load_history
from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.inventory.exceptions import EntityNotFoundError
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder, SupplierCondition

_ZERO = Decimal("0.000")


class ForecastInputs(NamedTuple):
    """Полный набор исходных данных для расчёта прогноза."""

    item: Item
    location: Location
    batches: list[BatchSnapshot]
    movements: list[MovementSnapshot]
    procurement_context: ProcurementContext


def load_procurement_context(
    session: Session,
    item_id: int,
    location_id: int,
    as_of: date,
) -> ProcurementContext:
    """Загружает условия основного поставщика, последнюю цену и заказы в пути."""
    condition: SupplierCondition | None = (
        session.query(SupplierCondition)
        .filter(
            SupplierCondition.item_id == item_id,
            SupplierCondition.is_primary.is_(True),
        )
        .first()
    )

    supplier_str_id: str | None = None
    supplier_name: str | None = None
    lead_time_days: int | None = None
    package_size: Decimal | None = None
    min_order_qty: Decimal | None = None
    unit_price: Decimal | None = None
    price_source: str | None = None

    if condition is not None:
        supplier: Supplier | None = (
            condition.supplier
            if condition.supplier is not None
            else session.get(Supplier, condition.supplier_id)
        )
        if supplier is not None:
            supplier_str_id = supplier.supplier_id
            supplier_name = supplier.name

        lead_time_days = condition.lead_time_days
        package_size = condition.package_size
        min_order_qty = condition.min_order_qty

        # Поиск последнего активного поступления данного поставщика до as_of включительно
        supplier_id_expr = case(
            (Movement.purchase_order_id.isnot(None), PurchaseOrder.supplier_id),
            else_=Movement.supplier_id,
        )

        receipt_movement: Movement | None = (
            session.query(Movement)
            .outerjoin(PurchaseOrder, Movement.purchase_order_id == PurchaseOrder.id)
            .join(Batch, Movement.batch_id == Batch.id)
            .filter(
                Movement.item_id == item_id,
                Movement.type == "receipt",
                Movement.status == "active",
                Movement.operation_date <= as_of,
                supplier_id_expr == condition.supplier_id,
            )
            .order_by(Movement.operation_date.desc(), Movement.id.desc())
            .first()
        )

        if receipt_movement is not None and receipt_movement.batch is not None:
            unit_price = receipt_movement.batch.unit_price
            price_source = "receipt"
        elif condition.estimated_price is not None:
            unit_price = condition.estimated_price
            price_source = "estimated"

    # Загрузка заказов поставщикам для товара и объекта
    orders: list[PurchaseOrder] = (
        session.query(PurchaseOrder)
        .filter(
            PurchaseOrder.item_id == item_id,
            PurchaseOrder.location_id == location_id,
            PurchaseOrder.status != "cancelled",
            PurchaseOrder.pending_qty > _ZERO,
        )
        .order_by(PurchaseOrder.expected_date.asc(), PurchaseOrder.id.asc())
        .all()
    )

    pending_orders: list[IncomingOrderSnapshot] = []
    delayed_orders: list[IncomingOrderSnapshot] = []

    for order in orders:
        snapshot = IncomingOrderSnapshot(
            order_id=order.id,
            doc_number=order.doc_number,
            expected_date=order.expected_date,
            pending_qty=order.pending_qty,
            unit_price=order.unit_price,
        )
        if order.expected_date <= as_of:
            delayed_orders.append(snapshot)
        else:
            pending_orders.append(snapshot)

    return ProcurementContext(
        supplier_id=supplier_str_id,
        supplier_name=supplier_name,
        lead_time_days=lead_time_days,
        package_size=package_size,
        min_order_qty=min_order_qty,
        unit_price=unit_price,
        price_source=price_source,
        pending_orders=tuple(pending_orders),
        delayed_orders=tuple(delayed_orders),
    )


def load_forecast_inputs(
    session: Session,
    sku: str,
    location_code: str,
    as_of: date,
) -> ForecastInputs:
    """Загружает исходные данные товара, склада, историю и контекст закупки."""
    item: Item | None = session.query(Item).filter(Item.sku == sku).first()
    if item is None:
        raise EntityNotFoundError("Item", sku)

    location: Location | None = (
        session.query(Location).filter(Location.code == location_code).first()
    )
    if location is None:
        raise EntityNotFoundError("Location", location_code)

    _, _, b_snaps, m_snaps = load_history(session, item.id, location.id)
    procurement_context = load_procurement_context(session, item.id, location.id, as_of)

    return ForecastInputs(
        item=item,
        location=location,
        batches=b_snaps,
        movements=m_snaps,
        procurement_context=procurement_context,
    )
