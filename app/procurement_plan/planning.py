"""Чистая логика дневного планирования повторных закупок для пары «товар + объект»."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.api.plan_schemas import PlanItemSchema
from app.forecasting.daily_fefo import simulate_daily_fefo
from app.forecasting.domain import (
    IncomingOrderSnapshot,
    compute_horizon_dates,
)
from app.inventory.domain import BatchSnapshot
from app.procurement.rounding import (
    QTY_QUANT,
    ZERO_QTY,
    round_order_quantity,
)
from app.procurement_plan.dates import compute_coverage_interval
from app.procurement_plan.domain import PairPlanResult
from app.procurement_plan.item_builder import build_plan_item
from app.procurement_plan.undated import plan_undated_pair_procurement
from app.procurement_plan.warnings import (
    WARN_NO_DEMAND_HISTORY,
    WARN_ORDER_DELAYED,
    WARN_PRICE_UNKNOWN,
    format_temporary_deficit_warning,
)


def plan_pair_procurement(
    as_of: date,
    horizon_months: int,
    service_days: int,
    sku: str,
    category: str,
    location: str,
    average_daily_consumption: Decimal,
    batches: Sequence[BatchSnapshot] = (),
    batch_stocks: dict[int, Decimal] | None = None,
    incoming_orders: Sequence[IncomingOrderSnapshot] = (),
    lead_time_days: int | None = None,
    package_size: Decimal | None = None,
    min_order_qty: Decimal | None = None,
    unit_price: Decimal | None = None,
    price_source: str | None = None,
    supplier_id: str | None = None,
    supplier_name: str | None = None,
) -> PairPlanResult:
    """Выполняет пошаговое дневное FEFO-планирование пары с месячной целью пополнения."""
    if average_daily_consumption <= ZERO_QTY:
        return PairPlanResult(
            items=(),
            warnings=(WARN_NO_DEMAND_HISTORY,),
        )

    pair_warnings: list[str] = []

    # Исходный остаток и объём ожидаемых поставок для метрик позиции
    initial_stock = sum((batch_stocks or {}).values(), ZERO_QTY)
    incoming_orders_qty = sum(
        (order.pending_qty for order in incoming_orders if order.pending_qty > ZERO_QTY),
        ZERO_QTY,
    )

    # Обработка задержанных заказов: expected_date <= as_of
    has_delayed_orders = any(
        order.expected_date <= as_of and order.pending_qty > ZERO_QTY for order in incoming_orders
    )
    if has_delayed_orders:
        pair_warnings.append(WARN_ORDER_DELAYED)

    # Недатированная позиция при отсутствии срока поставки: расчёт по FEFO
    if lead_time_days is None:
        return plan_undated_pair_procurement(
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
            has_delayed_orders=has_delayed_orders,
            pair_warnings=pair_warnings,
        )

    horizon_start, horizon_end, days_count = compute_horizon_dates(
        as_of=as_of,
        horizon_months=horizon_months,
    )

    raw_safety_stock = average_daily_consumption * Decimal(service_days)
    target_safety_stock = raw_safety_stock.quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
    threshold = raw_safety_stock if service_days > 0 else ZERO_QTY

    sim_batches = list(batches)
    sim_stocks = dict(batch_stocks or {})

    virtual_orders: list[IncomingOrderSnapshot] = []
    base_incoming_orders = [
        o for o in incoming_orders if o.expected_date > as_of and o.pending_qty > ZERO_QTY
    ]
    items: list[PlanItemSchema] = []

    min_search_date = horizon_start
    max_iterations = days_count + 5
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        all_incoming = base_incoming_orders + virtual_orders
        fefo_res = simulate_daily_fefo(
            as_of=as_of,
            average_daily_consumption=average_daily_consumption,
            batches=sim_batches,
            batch_stocks=sim_stocks,
            incoming_orders=all_incoming,
            horizon_months=horizon_months,
        )

        drop_step = None
        for step in fefo_res.daily_steps:
            if step.date < min_search_date:
                continue
            if service_days > 0 and step.closing_stock < threshold:
                drop_step = step
                break
            if service_days == 0 and (
                step.closing_stock <= ZERO_QTY or step.daily_deficit > ZERO_QTY
            ):
                drop_step = step
                break

        if drop_step is None:
            break

        drop_date = drop_step.date
        calc_order_date = drop_date - timedelta(days=lead_time_days)
        order_date = max(as_of, calc_order_date)
        delivery_date = order_date + timedelta(days=lead_time_days)

        is_early_order = calc_order_date < as_of

        # Фактический дефицит: строго дни с непокрытым расходом (daily_deficit > 0)
        actual_deficit_steps = [
            s
            for s in fefo_res.daily_steps
            if s.date <= delivery_date and s.daily_deficit > ZERO_QTY
        ]
        has_actual_deficit = is_early_order and len(actual_deficit_steps) > 0
        deficit_start = actual_deficit_steps[0].date if has_actual_deficit else None

        if has_actual_deficit and deficit_start is not None:
            deficit_warn = format_temporary_deficit_warning(deficit_start, delivery_date)
            if deficit_warn not in pair_warnings:
                pair_warnings.append(deficit_warn)

        if delivery_date > horizon_end:
            pair_warnings.append(
                f"DELIVERY_BEYOND_HORIZON: Ближайшая возможная поставка ({delivery_date}) "
                f"позднее конца горизонта ({horizon_end}); потребность не обеспечена"
            )
            break

        coverage_start, coverage_end = compute_coverage_interval(delivery_date, horizon_end)

        deficit_in_window = sum(
            (
                s.daily_deficit
                for s in fefo_res.daily_steps
                if coverage_start <= s.date <= coverage_end
            ),
            ZERO_QTY,
        )
        closing_stock_at_end = next(
            s.closing_stock for s in reversed(fefo_res.daily_steps) if s.date == coverage_end
        )

        needed_for_deficit = deficit_in_window
        needed_for_stock = deficit_in_window + target_safety_stock - closing_stock_at_end
        raw_quantity = max(needed_for_deficit, needed_for_stock)

        if raw_quantity <= ZERO_QTY:
            min_search_date = coverage_end + timedelta(days=1)
            continue

        quantity = round_order_quantity(
            raw_quantity,
            package_size=package_size,
            min_order_qty=min_order_qty,
        )
        if quantity <= ZERO_QTY:
            min_search_date = coverage_end + timedelta(days=1)
            continue

        if unit_price is None and WARN_PRICE_UNKNOWN not in pair_warnings:
            pair_warnings.append(WARN_PRICE_UNKNOWN)

        item_schema = build_plan_item(
            sku=sku,
            category=category,
            location=location,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            order_date=order_date,
            delivery_date=delivery_date,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            raw_quantity=raw_quantity,
            quantity=quantity,
            unit_price=unit_price,
            price_source=price_source,
            average_daily_consumption=average_daily_consumption,
            lead_time_days=lead_time_days,
            service_days=service_days,
            target_safety_stock=target_safety_stock,
            drop_date=drop_date,
            package_size=package_size,
            min_order_qty=min_order_qty,
            has_actual_deficit=has_actual_deficit,
            deficit_start=deficit_start,
            has_delayed_orders=has_delayed_orders,
            initial_stock=initial_stock,
            incoming_orders_qty=incoming_orders_qty,
        )
        items.append(item_schema)

        virtual_order = IncomingOrderSnapshot(
            order_id=-(len(virtual_orders) + 1),
            doc_number=f"VIRT-PLAN-{len(virtual_orders) + 1}",
            expected_date=delivery_date,
            pending_qty=quantity,
            unit_price=item_schema.unit_price,
        )
        virtual_orders.append(virtual_order)
        min_search_date = delivery_date + timedelta(days=1)

    return PairPlanResult(
        items=tuple(items),
        warnings=tuple(pair_warnings),
    )
