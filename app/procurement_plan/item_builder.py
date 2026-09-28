"""Построение схемы позиции плана закупок с метриками и предупреждениями."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.api.plan_schemas import PlanItemSchema
from app.procurement.rounding import (
    QTY_QUANT,
    calculate_total_cost,
    round_unit_price,
)
from app.procurement_plan.warnings import (
    WARN_ORDER_DELAYED,
    WARN_PRICE_UNKNOWN,
    format_temporary_deficit_warning,
)


def build_plan_item(
    sku: str,
    category: str,
    location: str,
    supplier_id: str | None,
    supplier_name: str | None,
    order_date: date,
    delivery_date: date,
    coverage_start: date,
    coverage_end: date,
    raw_quantity: Decimal,
    quantity: Decimal,
    unit_price: Decimal | None,
    price_source: str | None,
    average_daily_consumption: Decimal,
    lead_time_days: int,
    service_days: int,
    target_safety_stock: Decimal,
    drop_date: date,
    package_size: Decimal | None,
    min_order_qty: Decimal | None,
    is_early_deficit: bool,
    has_delayed_orders: bool,
) -> PlanItemSchema:
    """Создаёт объект позиции плана с расчётом стоимости, метрик и предупреждений."""
    rounded_price = round_unit_price(unit_price)
    total_cost = calculate_total_cost(quantity, rounded_price)

    item_warnings: list[str] = []
    if is_early_deficit:
        item_warnings.append(format_temporary_deficit_warning(drop_date, delivery_date))
    if has_delayed_orders:
        item_warnings.append(WARN_ORDER_DELAYED)
    if rounded_price is None:
        item_warnings.append(WARN_PRICE_UNKNOWN)

    coverage_days = (coverage_end - coverage_start).days + 1
    metrics: dict[str, Any] = {
        "average_daily_consumption": str(average_daily_consumption),
        "lead_time_days": lead_time_days,
        "service_days": service_days,
        "package_size": str(package_size) if package_size is not None else None,
        "min_order_qty": str(min_order_qty) if min_order_qty is not None else None,
        "safety_stock": str(target_safety_stock),
        "drop_date": drop_date.isoformat(),
        "coverage_days": coverage_days,
    }
    if is_early_deficit:
        metrics["deficit_start"] = drop_date.isoformat()
        metrics["deficit_end"] = (
            (delivery_date - timedelta(days=1)).isoformat()
            if delivery_date > drop_date
            else drop_date.isoformat()
        )
        metrics["deficit_delivery_date"] = delivery_date.isoformat()

    return PlanItemSchema(
        sku=sku,
        category=category,
        location=location,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        supplier=supplier_name or supplier_id,
        order_date=order_date,
        delivery_date=delivery_date,
        expected_date=delivery_date,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        is_undated=False,
        raw_quantity=raw_quantity.quantize(QTY_QUANT, rounding=ROUND_HALF_UP),
        quantity=quantity,
        recommended_qty=quantity,
        unit_price=rounded_price,
        price_source=price_source,
        total_cost=total_cost,
        metrics=metrics,
        warnings=item_warnings,
    )
