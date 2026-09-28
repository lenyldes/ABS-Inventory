"""Чистый расчёт истории потребления, среднего расхода и запаса в днях."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.forecasting.domain import ConsumptionMetrics
from app.inventory.domain import MovementSnapshot

_ZERO_QTY = Decimal("0.000")
_ZERO_AVG = Decimal("0.000000")
_DAYS_WINDOW = 90
_DECIMAL_WINDOW = Decimal("90")
_AVG_QUANTIZE = Decimal("0.000001")
_DAYS_STOCK_QUANTIZE = Decimal("0.1")


def calculate_consumption_metrics(
    movements: Sequence[MovementSnapshot],
    as_of: date,
    available_stock: Decimal | None = None,
) -> ConsumptionMetrics:
    """Вычисляет показатели чистого потребления за 90 дней, полноту истории и дни запаса.

    Параметры:
        movements: последовательность движений товара на объекте.
        as_of: дата актуальности расчёта.
        available_stock: доступный остаток на складе на дату as_of (если известен).

    Возвращает:
        ConsumptionMetrics со средним суточным расходом, суммарным расходом за 90 дней,
        данными о полноте истории и расчётным запасом в днях.
    """
    # Учитываем только активные движения, известные на контрольную дату
    active_movements = [m for m in movements if m.status == "active" and m.operation_date <= as_of]

    # Полнота истории по первому известному активному движению любого типа
    if active_movements:
        first_movement_date = min(m.operation_date for m in active_movements)
        history_days = (as_of - first_movement_date).days
        is_history_complete = history_days >= _DAYS_WINDOW
    else:
        first_movement_date = None
        history_days = 0
        is_history_complete = False

    # Границы 90-дневного календарного окна потребления [start_date, as_of]
    start_date = as_of - timedelta(days=_DAYS_WINDOW - 1)

    # Агрегируем возвраты по parent_movement_id
    returns_by_parent: dict[int, Decimal] = defaultdict(lambda: _ZERO_QTY)
    for m in active_movements:
        if m.type == "return" and m.parent_movement_id is not None:
            returns_by_parent[m.parent_movement_id] += m.quantity

    # Суммируем чистый расход для consume внутри 90-дневного окна
    total_consumption = _ZERO_QTY
    for m in active_movements:
        if m.type == "consume" and start_date <= m.operation_date <= as_of:
            returned_qty = returns_by_parent.get(m.id, _ZERO_QTY) if m.id is not None else _ZERO_QTY
            net_qty = max(_ZERO_QTY, m.quantity - returned_qty)
            total_consumption += net_qty

    total_consumption_90d = total_consumption.quantize(_ZERO_QTY)

    # Средний суточный расход: знаменатель всегда 90
    if total_consumption_90d <= _ZERO_QTY:
        average_daily_consumption = _ZERO_AVG
    else:
        average_daily_consumption = (total_consumption_90d / _DECIMAL_WINDOW).quantize(
            _AVG_QUANTIZE, rounding=ROUND_HALF_UP
        )

    # Дни запаса: available_stock / a при положительном среднем расходе
    if available_stock is not None and average_daily_consumption > _ZERO_AVG:
        days_of_stock = (available_stock / average_daily_consumption).quantize(
            _DAYS_STOCK_QUANTIZE, rounding=ROUND_HALF_UP
        )
    else:
        days_of_stock = None

    return ConsumptionMetrics(
        average_daily_consumption=average_daily_consumption,
        total_consumption_90d=total_consumption_90d,
        history_days=history_days,
        is_history_complete=is_history_complete,
        first_movement_date=first_movement_date,
        days_of_stock=days_of_stock,
    )
