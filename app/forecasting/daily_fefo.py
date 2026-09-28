"""Чистые календарные и суточные расчёты моделирования запасов по FEFO."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.forecasting.domain import (
    DailyFefoResult,
    DailyForecastStep,
    IncomingOrderSnapshot,
    compute_horizon_dates,
)
from app.inventory.domain import BatchSnapshot

_ZERO_QTY = Decimal("0.000")


@dataclass
class _SimulationLot:
    """Внутреннее состояние учётной партии или ожидаемой поставки при симуляции."""

    lot_id: str
    expiry_date: date | None
    receipt_date: date
    created_at: datetime
    lot_type: int  # 0 - складская партия, 1 - ожидаемая поставка
    remaining_qty: Decimal


def _lot_fefo_sort_key(
    lot: _SimulationLot,
) -> tuple[int, date, date, int, datetime, str]:
    """Ключ детерминированной сортировки лотов по правилу FEFO."""
    has_no_expiry = 1 if lot.expiry_date is None else 0
    expiry = lot.expiry_date or date.max
    return (
        has_no_expiry,
        expiry,
        lot.receipt_date,
        lot.lot_type,
        lot.created_at,
        lot.lot_id,
    )


def simulate_daily_fefo(
    as_of: date,
    average_daily_consumption: Decimal,
    batches: Sequence[BatchSnapshot],
    batch_stocks: dict[int, Decimal] | None = None,
    incoming_orders: Sequence[IncomingOrderSnapshot] = (),
    horizon_days: int | None = None,
    horizon_months: int | None = None,
) -> DailyFefoResult:
    """Моделирует посуточное потребление и движение запасов по алгоритму FEFO."""
    if average_daily_consumption < _ZERO_QTY:
        raise ValueError("Среднесуточный расход не может быть отрицательным")

    horizon_start, horizon_end, days_count = compute_horizon_dates(
        as_of=as_of,
        horizon_days=horizon_days,
        horizon_months=horizon_months,
    )

    stocks_map = batch_stocks or {}
    active_lots: list[_SimulationLot] = []
    for b in batches:
        qty = stocks_map.get(b.id, _ZERO_QTY)
        if qty > _ZERO_QTY:
            active_lots.append(
                _SimulationLot(
                    lot_id=f"batch_{b.id}",
                    expiry_date=b.expiry_date,
                    receipt_date=b.receipt_date,
                    created_at=b.created_at or datetime.min,
                    lot_type=0,
                    remaining_qty=qty,
                )
            )

    future_orders_by_date: dict[date, list[IncomingOrderSnapshot]] = {}
    for order in incoming_orders:
        if order.expected_date > as_of and order.pending_qty > _ZERO_QTY:
            future_orders_by_date.setdefault(order.expected_date, []).append(order)

    daily_steps: list[DailyForecastStep] = []
    current_date = horizon_start
    daily_demand = average_daily_consumption
    stockout_date: date | None = None
    first_deficit_date: date | None = None
    total_incoming = _ZERO_QTY
    total_consumption = _ZERO_QTY
    total_expired = _ZERO_QTY
    total_deficit = _ZERO_QTY
    has_temporary_stockout = False

    while current_date <= horizon_end:
        # 1. Списание просрочки: партии с expiry_date < current_date
        expired_today = _ZERO_QTY
        surviving_lots: list[_SimulationLot] = []
        for lot in active_lots:
            if lot.expiry_date is not None and lot.expiry_date < current_date:
                expired_today += lot.remaining_qty
            else:
                surviving_lots.append(lot)
        active_lots = surviving_lots

        # 2. Приход ожидаемых поставок: expected_date == current_date
        incoming_today = _ZERO_QTY
        orders_today = future_orders_by_date.get(current_date, [])
        for ord_item in orders_today:
            inc_qty = ord_item.pending_qty
            incoming_today += inc_qty
            active_lots.append(
                _SimulationLot(
                    lot_id=f"order_{ord_item.order_id}",
                    expiry_date=None,
                    receipt_date=ord_item.expected_date,
                    created_at=datetime.min,
                    lot_type=1,
                    remaining_qty=inc_qty,
                )
            )

        # 3. Дневной расход: списание по FEFO
        active_lots.sort(key=_lot_fefo_sort_key)
        needed = daily_demand
        consumed_today = _ZERO_QTY

        for lot in active_lots:
            if needed <= _ZERO_QTY:
                break
            take = min(lot.remaining_qty, needed)
            lot.remaining_qty -= take
            consumed_today += take
            needed -= take

        active_lots = [lot for lot in active_lots if lot.remaining_qty > _ZERO_QTY]
        deficit_today = daily_demand - consumed_today
        closing_stock = sum((lot.remaining_qty for lot in active_lots), _ZERO_QTY)

        total_incoming += incoming_today
        total_consumption += consumed_today
        total_expired += expired_today
        total_deficit += deficit_today
        if daily_demand > _ZERO_QTY and closing_stock <= _ZERO_QTY and stockout_date is None:
            stockout_date = current_date
        if deficit_today > _ZERO_QTY and first_deficit_date is None:
            first_deficit_date = current_date
        if (
            first_deficit_date is not None
            and current_date > first_deficit_date
            and incoming_today > _ZERO_QTY
        ):
            has_temporary_stockout = True

        daily_steps.append(
            DailyForecastStep(
                date=current_date,
                consumption=consumed_today,
                incoming=incoming_today,
                expired=expired_today,
                closing_stock=closing_stock,
                daily_deficit=deficit_today,
            )
        )
        current_date += timedelta(days=1)

    return DailyFefoResult(
        daily_steps=tuple(daily_steps),
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        days_count=days_count,
        stockout_date=stockout_date,
        first_deficit_date=first_deficit_date,
        total_incoming=total_incoming,
        total_consumption=total_consumption,
        total_expired=total_expired,
        total_deficit=total_deficit,
        has_temporary_stockout=has_temporary_stockout,
    )
