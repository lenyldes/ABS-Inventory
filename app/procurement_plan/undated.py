"""Чистая логика расчёта недатированной позиции плана при неизвестном сроке поставки."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.api.plan_schemas import PlanItemSchema
from app.forecasting.domain import compute_horizon_dates
from app.procurement.rounding import (
    QTY_QUANT,
    ZERO_QTY,
    calculate_total_cost,
    round_order_quantity,
    round_unit_price,
)
from app.procurement_plan.warnings import (
    WARN_LEAD_TIME_UNKNOWN,
    WARN_PRICE_UNKNOWN,
)


def calculate_undated_item(
    as_of: date,
    sku: str,
    category: str,
    location: str,
    average_daily_consumption: Decimal,
    usable_stock: Decimal = ZERO_QTY,
    service_days: int = 0,
    package_size: Decimal | None = None,
    min_order_qty: Decimal | None = None,
    unit_price: Decimal | None = None,
    price_source: str | None = None,
    supplier_id: str | None = None,
    supplier_name: str | None = None,
    horizon_months: int = 1,
) -> PlanItemSchema:
    """Формирует одну недатированную позицию с оценкой объёма на весь горизонт."""
    _, _, days_count = compute_horizon_dates(as_of=as_of, horizon_months=horizon_months)
    raw_forecast = average_daily_consumption * Decimal(days_count)
    raw_safety = average_daily_consumption * Decimal(service_days)

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
        "usable_stock": str(usable_stock),
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
