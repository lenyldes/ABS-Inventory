"""Модуль вычисления складских рисков, предупреждений и ограничений данных."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from app.forecasting.alert_rules_deficit import (
    evaluate_deficit_alerts,
    evaluate_history_alerts,
)
from app.forecasting.alert_rules_shelf import evaluate_shelf_life_alerts
from app.forecasting.consumption import calculate_consumption_metrics
from app.forecasting.daily_fefo import simulate_daily_fefo
from app.forecasting.domain import (
    AlertItem,
    ProcurementContext,
    compute_horizon_dates,
)
from app.forecasting.order_calculation import calculate_order_recommendation
from app.inventory.domain import BatchSnapshot, MovementSnapshot, StockBalance


def calculate_item_alerts(
    sku: str,
    location: str,
    as_of: date,
    stock_balance: StockBalance,
    movements: Sequence[MovementSnapshot],
    procurement: ProcurementContext,
    horizon_days: int | None = None,
    shelf_life_days_threshold: int = 30,
    no_movement_days_threshold: int = 90,
    batches: Sequence[BatchSnapshot] | None = None,
) -> list[AlertItem]:
    """Вычисляет предупреждения о рисках запасов и ограничениях данных по товару и объекту."""
    if horizon_days is not None and horizon_days < 1:
        raise ValueError("horizon_days должен быть >= 1")
    if shelf_life_days_threshold < 1:
        raise ValueError("shelf_life_days_threshold должен быть >= 1")
    if no_movement_days_threshold < 1:
        raise ValueError("no_movement_days_threshold должен быть >= 1")

    lead_time = procurement.lead_time_days
    if horizon_days is not None:
        effective_horizon_days = horizon_days
    else:
        effective_horizon_days = max(30, lead_time + 1) if lead_time is not None else 30

    _, horizon_end, _ = compute_horizon_dates(as_of=as_of, horizon_days=effective_horizon_days)

    consumption = calculate_consumption_metrics(
        movements=movements,
        as_of=as_of,
        available_stock=stock_balance.available_stock,
    )
    a = consumption.average_daily_consumption
    avail = stock_balance.available_stock

    if batches is not None:
        sim_batches = list(batches)
        sim_stocks = {b.id: Decimal("0.000") for b in sim_batches}
        for bs in stock_balance.batches:
            sim_stocks[bs.batch_id] = bs.available_quantity
    else:
        sim_batches = [
            BatchSnapshot(
                id=bs.batch_id,
                item_id=0,
                location_id=0,
                batch_number=bs.batch_number,
                receipt_date=bs.receipt_date,
                expiry_date=bs.expiry_date,
                unit_price=bs.unit_price,
                receipt_doc_number=bs.receipt_doc_number,
            )
            for bs in stock_balance.batches
        ]
        sim_stocks = {bs.batch_id: bs.available_quantity for bs in stock_balance.batches}

    daily_fefo = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=a,
        batches=sim_batches,
        batch_stocks=sim_stocks,
        incoming_orders=procurement.pending_orders,
        horizon_days=effective_horizon_days,
    )

    order_rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=a,
        days_count=effective_horizon_days,
        service_days=0,
        lead_time_days=lead_time,
        package_size=procurement.package_size,
        min_order_qty=procurement.min_order_qty,
        unit_price=procurement.unit_price,
        available_stock=avail,
        daily_fefo=daily_fefo,
    )

    alerts: list[AlertItem] = []

    # 1-2. stockout, potential_stockout
    deficit_alerts = evaluate_deficit_alerts(
        sku=sku,
        location=location,
        as_of=as_of,
        available_stock=avail,
        average_daily_consumption=a,
        days_of_stock=consumption.days_of_stock,
        lead_time_days=lead_time,
        effective_horizon_days=effective_horizon_days,
        horizon_end=horizon_end,
        stockout_date=daily_fefo.stockout_date,
        reorder_point=order_rec.reorder_point,
        order_date=order_rec.order_date,
    )
    alerts.extend(deficit_alerts)

    # 3-5. expired, expiring_soon, writeoff_risk
    shelf_life_alerts = evaluate_shelf_life_alerts(
        sku=sku,
        location=location,
        as_of=as_of,
        batches=stock_balance.batches,
        shelf_life_days_threshold=shelf_life_days_threshold,
        total_expired_forecast=daily_fefo.total_expired,
        effective_horizon_days=effective_horizon_days,
        horizon_end=horizon_end,
    )
    alerts.extend(shelf_life_alerts)

    # 6-7. no_movement, incomplete_history
    history_alerts = evaluate_history_alerts(
        sku=sku,
        location=location,
        as_of=as_of,
        current_stock=stock_balance.current_stock,
        movements=movements,
        consumption_metrics=consumption,
        no_movement_days_threshold=no_movement_days_threshold,
    )
    alerts.extend(history_alerts)

    return alerts
