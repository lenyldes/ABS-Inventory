"""Правила оценки дефицита запаса, движения и полноты истории."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from app.forecasting.domain import AlertItem, ConsumptionMetrics
from app.inventory.domain import MovementSnapshot

_DAYS_WINDOW = 90


def evaluate_deficit_alerts(
    sku: str,
    location: str,
    as_of: date,
    available_stock: Decimal,
    average_daily_consumption: Decimal,
    days_of_stock: Decimal | None,
    lead_time_days: int | None,
    effective_horizon_days: int,
    horizon_end: date,
    stockout_date: date | None,
    reorder_point: Decimal | None,
    order_date: date | None,
    calculation_limit: str | None = None,
) -> list[AlertItem]:
    """Формирует предупреждения о критическом и потенциальном дефиците запаса."""
    alerts: list[AlertItem] = []
    a = average_daily_consumption
    avail = available_stock

    is_stockout = False
    stockout_msg = ""
    if avail <= Decimal("0") and a > Decimal("0"):
        is_stockout = True
        stockout_msg = "Критический дефицит: доступный запас равен нулю при наличии расхода"
    elif lead_time_days is not None and a > Decimal("0") and stockout_date is not None:
        if stockout_date <= as_of + timedelta(days=lead_time_days):
            is_stockout = True
            stockout_msg = "Критический дефицит: исчерпание запаса до возможного прибытия заказа"

    if is_stockout:
        stockout_metrics: dict[str, object] = {
            "available_stock": str(avail),
            "average_daily_consumption": str(a),
            "lead_time_days": lead_time_days,
            "days_of_stock": str(days_of_stock) if days_of_stock is not None else None,
            "horizon_days": effective_horizon_days,
            "horizon_end": horizon_end.isoformat(),
        }
        if stockout_date is not None:
            stockout_metrics["stockout_date"] = stockout_date.isoformat()
        if calculation_limit is not None:
            stockout_metrics["calculation_limit"] = calculation_limit

        alerts.append(
            AlertItem(
                id=f"alert-stockout-{location}-{sku}-{as_of.isoformat()}",
                type="stockout",
                level="critical",
                sku=sku,
                location=location,
                batch_id=None,
                message=stockout_msg,
                metrics=stockout_metrics,
                as_of=as_of,
            )
        )
    elif (
        reorder_point is not None
        and avail < reorder_point
        and order_date is not None
        and order_date > as_of
    ):
        alerts.append(
            AlertItem(
                id=f"alert-potential_stockout-{location}-{sku}-{as_of.isoformat()}",
                type="potential_stockout",
                level="warning",
                sku=sku,
                location=location,
                batch_id=None,
                message="Потенциальный дефицит: доступный запас ниже точки заказа",
                metrics={
                    "available_stock": str(avail),
                    "reorder_point": str(reorder_point),
                    "order_date": order_date.isoformat(),
                    "average_daily_consumption": str(a),
                    "lead_time_days": lead_time_days,
                    "days_of_stock": str(days_of_stock) if days_of_stock is not None else None,
                    "horizon_days": effective_horizon_days,
                    "horizon_end": horizon_end.isoformat(),
                    **({"calculation_limit": calculation_limit} if calculation_limit else {}),
                },
                as_of=as_of,
            )
        )

    return alerts


def evaluate_history_alerts(
    sku: str,
    location: str,
    as_of: date,
    current_stock: Decimal,
    movements: Sequence[MovementSnapshot],
    consumption_metrics: ConsumptionMetrics,
    no_movement_days_threshold: int,
) -> list[AlertItem]:
    """Формирует предупреждения об отсутствии движения и неполной истории."""
    alerts: list[AlertItem] = []

    if current_stock > Decimal("0"):
        threshold_start_date = as_of - timedelta(days=no_movement_days_threshold - 1)
        has_consume = any(
            m.status == "active"
            and m.type == "consume"
            and threshold_start_date <= m.operation_date <= as_of
            for m in movements
        )
        if not has_consume:
            alerts.append(
                AlertItem(
                    id=f"alert-no_movement-{location}-{sku}-{as_of.isoformat()}",
                    type="no_movement",
                    level="info",
                    sku=sku,
                    location=location,
                    batch_id=None,
                    message=(
                        f"Отсутствие движения: за последние {no_movement_days_threshold} "
                        "дн. не было операций расхода"
                    ),
                    metrics={
                        "current_stock": str(current_stock),
                        "no_movement_days_threshold": no_movement_days_threshold,
                    },
                    as_of=as_of,
                )
            )

    if not consumption_metrics.is_history_complete:
        alerts.append(
            AlertItem(
                id=f"alert-incomplete_history-{location}-{sku}-{as_of.isoformat()}",
                type="incomplete_history",
                level="info",
                sku=sku,
                location=location,
                batch_id=None,
                message=(
                    f"Неполная история потребления: доступно {consumption_metrics.history_days} "
                    "из 90 дней, возможен риск занижения расхода"
                ),
                metrics={
                    "history_days": consumption_metrics.history_days,
                    "required_days": _DAYS_WINDOW,
                    "first_movement_date": (
                        consumption_metrics.first_movement_date.isoformat()
                        if consumption_metrics.first_movement_date
                        else None
                    ),
                },
                as_of=as_of,
            )
        )

    return alerts
