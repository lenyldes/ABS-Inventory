"""Адаптер снимка базы данных для вызова расчёта плана повторных закупок."""

from datetime import date

from app.forecasting.consumption import calculate_consumption_metrics
from app.forecasting.domain import IncomingOrderSnapshot
from app.inventory.calculator import calculate_stock_balance
from app.procurement_plan.domain import PlanItemLocationPair
from app.procurement_plan.planning import PairPlanResult, plan_pair_procurement


def plan_pair_from_snapshot(
    pair: PlanItemLocationPair,
    as_of: date,
    horizon_months: int,
    service_days: int,
) -> PairPlanResult:
    """Адаптирует данные согласованного снимка пары «товар + объект» к расчёту плана."""
    balance = calculate_stock_balance(
        batches=pair.batches,
        movements=pair.movements,
        as_of=as_of,
    )
    batch_stocks = {b.batch_id: b.available_quantity for b in balance.batches}

    consumption_metrics = calculate_consumption_metrics(
        movements=pair.movements,
        as_of=as_of,
        available_stock=balance.available_stock,
    )

    incoming_orders: list[IncomingOrderSnapshot] = []
    for order in pair.active_orders:
        incoming_orders.append(
            IncomingOrderSnapshot(
                order_id=order.order_id,
                doc_number=order.doc_number,
                expected_date=order.expected_date,
                pending_qty=order.pending_qty,
                unit_price=order.unit_price,
            )
        )

    ctx = pair.procurement_context
    result = plan_pair_procurement(
        as_of=as_of,
        horizon_months=horizon_months,
        service_days=service_days,
        sku=pair.item.sku,
        category=pair.item.category,
        location=pair.location.code,
        average_daily_consumption=consumption_metrics.average_daily_consumption,
        batches=pair.batches,
        batch_stocks=batch_stocks,
        incoming_orders=incoming_orders,
        lead_time_days=ctx.lead_time_days,
        package_size=ctx.package_size,
        min_order_qty=ctx.min_order_qty,
        unit_price=ctx.unit_price,
        price_source=ctx.price_source,
        supplier_id=ctx.supplier_id,
        supplier_name=ctx.supplier_name,
    )

    if not consumption_metrics.is_history_complete:
        history_warn = (
            f"INCOMPLETE_HISTORY: История движений неполная "
            f"({consumption_metrics.history_days} дн. из 90)"
        )
        all_warnings = (history_warn,) + result.warnings
        return PairPlanResult(
            items=result.items,
            warnings=all_warnings,
        )

    return result
