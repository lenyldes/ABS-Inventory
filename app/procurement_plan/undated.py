"""Чистая логика расчёта недатированной позиции плана при неизвестном сроке поставки."""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.api.plan_schemas import PlanItemSchema
from app.forecasting.daily_fefo import simulate_daily_fefo
from app.forecasting.domain import IncomingOrderSnapshot
from app.inventory.domain import BatchSnapshot
from app.procurement.rounding import (
    QTY_QUANT,
    ZERO_QTY,
    calculate_total_cost,
    round_order_quantity,
    round_unit_price,
)
from app.procurement_plan.domain import PairPlanResult
from app.procurement_plan.warnings import (
    WARN_LEAD_TIME_UNKNOWN,
    WARN_ORDER_DELAYED,
    WARN_PRICE_UNKNOWN,
)


def calculate_undated_item(
    as_of: date,
    sku: str,
    category: str,
    location: str,
    average_daily_consumption: Decimal,
    batches: Sequence[BatchSnapshot] = (),
    batch_stocks: dict[int, Decimal] | None = None,
    incoming_orders: Sequence[IncomingOrderSnapshot] = (),
    service_days: int = 0,
    package_size: Decimal | None = None,
    min_order_qty: Decimal | None = None,
    unit_price: Decimal | None = None,
    price_source: str | None = None,
    supplier_id: str | None = None,
    supplier_name: str | None = None,
    horizon_months: int = 1,
    initial_stock: Decimal = ZERO_QTY,
    incoming_orders_qty: Decimal = ZERO_QTY,
) -> PlanItemSchema:
    """Формирует одну недатированную позицию с оценкой объёма по правилам FEFO."""
    fefo_res = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=average_daily_consumption,
        batches=batches,
        batch_stocks=batch_stocks,
        incoming_orders=incoming_orders,
        horizon_months=horizon_months,
    )

    days_count = fefo_res.days_count
    raw_forecast = average_daily_consumption * Decimal(days_count)
    raw_safety = average_daily_consumption * Decimal(service_days)

    tot_incoming = fefo_res.total_incoming
    tot_expired = fefo_res.total_expired
    usable_stock = max(ZERO_QTY, initial_stock + tot_incoming - tot_expired)

    raw_quantity = max(ZERO_QTY, raw_forecast + raw_safety - usable_stock)

    quantity = round_order_quantity(
        raw_quantity,
        package_size=package_size,
        min_order_qty=min_order_qty,
    )

    rounded_price = round_unit_price(unit_price)
    total_cost = calculate_total_cost(quantity, rounded_price)

    item_warnings: list[str] = [WARN_LEAD_TIME_UNKNOWN]
    if rounded_price is None:
        item_warnings.append(WARN_PRICE_UNKNOWN)

    metrics: dict[str, Any] = {
        "average_daily_consumption": str(average_daily_consumption),
        "lead_time_days": None,
        "service_days": service_days,
        "package_size": str(package_size) if package_size is not None else None,
        "min_order_qty": str(min_order_qty) if min_order_qty is not None else None,
        "horizon_months": horizon_months,
        "horizon_days": days_count,
        "initial_stock": str(initial_stock.quantize(QTY_QUANT)),
        "incoming_orders": str(incoming_orders_qty.quantize(QTY_QUANT)),
        "expected_orders_qty": str(incoming_orders_qty.quantize(QTY_QUANT)),
        "usable_stock": str(usable_stock.quantize(QTY_QUANT)),
        "total_expired": str(tot_expired.quantize(QTY_QUANT)),
        "is_undated": True,
    }

    return PlanItemSchema(
        sku=sku,
        category=category,
        location=location,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        supplier=supplier_name or supplier_id,
        order_date=None,
        delivery_date=None,
        expected_date=None,
        coverage_start=None,
        coverage_end=None,
        is_undated=True,
        raw_quantity=raw_quantity.quantize(QTY_QUANT, rounding=ROUND_HALF_UP),
        quantity=quantity,
        recommended_qty=quantity,
        unit_price=rounded_price,
        price_source=price_source,
        total_cost=total_cost,
        metrics=metrics,
        warnings=item_warnings,
    )


def plan_undated_pair_procurement(
    as_of: date,
    sku: str,
    category: str,
    location: str,
    average_daily_consumption: Decimal,
    batches: Sequence[BatchSnapshot] = (),
    batch_stocks: dict[int, Decimal] | None = None,
    incoming_orders: Sequence[IncomingOrderSnapshot] = (),
    service_days: int = 0,
    package_size: Decimal | None = None,
    min_order_qty: Decimal | None = None,
    unit_price: Decimal | None = None,
    price_source: str | None = None,
    supplier_id: str | None = None,
    supplier_name: str | None = None,
    horizon_months: int = 1,
    initial_stock: Decimal = ZERO_QTY,
    incoming_orders_qty: Decimal = ZERO_QTY,
    has_delayed_orders: bool = False,
    pair_warnings: Sequence[str] = (),
) -> PairPlanResult:
    """Выполняет расчёт недатированной позиции и формирует результат плана пары."""
    undated_item = calculate_undated_item(
        as_of=as_of,
        sku=sku,
        category=category,
        location=location,
        average_daily_consumption=average_daily_consumption,
        batches=batches,
        batch_stocks=batch_stocks,
        incoming_orders=incoming_orders,
        service_days=service_days,
        package_size=package_size,
        min_order_qty=min_order_qty,
        unit_price=unit_price,
        price_source=price_source,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        horizon_months=horizon_months,
        initial_stock=initial_stock,
        incoming_orders_qty=incoming_orders_qty,
    )
    res_warnings = list(pair_warnings)
    if has_delayed_orders and WARN_ORDER_DELAYED not in undated_item.warnings:
        undated_item.warnings.append(WARN_ORDER_DELAYED)
    if WARN_LEAD_TIME_UNKNOWN not in res_warnings:
        res_warnings.append(WARN_LEAD_TIME_UNKNOWN)
    if unit_price is None and WARN_PRICE_UNKNOWN not in res_warnings:
        res_warnings.append(WARN_PRICE_UNKNOWN)

    return PairPlanResult(
        items=(undated_item,),
        warnings=tuple(res_warnings),
    )
