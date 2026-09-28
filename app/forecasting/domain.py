"""Общий контракт данных и структуры предметной области прогнозирования."""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


def compute_horizon_dates(
    as_of: date,
    horizon_days: int | None = None,
    horizon_months: int | None = None,
) -> tuple[date, date, int]:
    """Вычисляет начальную, конечную дату и число дней горизонта прогноза.

    Прогноз всегда начинается с as_of + 1 день.
    При нехватке дней в целевом месяце сдвиг выполняется на последний день месяца
    (например, 31.01 + 1 мес. = 28.02 в невисокосный год).
    """
    if horizon_days is not None and horizon_months is not None:
        raise ValueError("Параметры horizon_days и horizon_months взаимоисключающие")
    if horizon_days is None and horizon_months is None:
        raise ValueError("Необходимо указать horizon_days либо horizon_months")

    horizon_start = as_of + timedelta(days=1)

    if horizon_days is not None:
        if horizon_days < 1:
            raise ValueError("horizon_days должен быть >= 1")
        horizon_end = as_of + timedelta(days=horizon_days)
        days_count = horizon_days
    else:
        assert horizon_months is not None
        if horizon_months < 1:
            raise ValueError("horizon_months должен быть >= 1")
        total_months = as_of.month + horizon_months - 1
        target_year = as_of.year + total_months // 12
        target_month = total_months % 12 + 1
        max_day = calendar.monthrange(target_year, target_month)[1]
        target_day = min(as_of.day, max_day)
        horizon_end = date(target_year, target_month, target_day)
        days_count = (horizon_end - as_of).days

    return horizon_start, horizon_end, days_count


@dataclass(frozen=True)
class ConsumptionMetrics:
    """Метрики потребления за 90-дневное окно."""

    average_daily_consumption: Decimal  # с точностью не менее 6 знаков
    total_consumption_90d: Decimal  # суммарный чистый расход за окно
    history_days: int  # число дней известной истории до as_of
    is_history_complete: bool  # True, если history_days >= 90
    first_movement_date: date | None  # дата первого движения товара на объекте
    days_of_stock: Decimal | None  # available_stock / a (1 знак) или None


@dataclass(frozen=True)
class DailyForecastStep:
    """Шаг суточного моделирования FEFO."""

    date: date
    consumption: Decimal  # фактически списанный суточный расход без округления
    incoming: Decimal  # поступившее количество ожидаемой поставки без округления
    expired: Decimal  # списано по сроку годности на начало дня без округления
    closing_stock: Decimal  # доступный остаток на конец дня без округления
    daily_deficit: Decimal  # непокрытый суточный дефицит без округления


@dataclass(frozen=True)
class DailyFefoResult:
    """Результат посуточного FEFO-моделирования на горизонте прогноза."""

    daily_steps: tuple[DailyForecastStep, ...]
    horizon_start: date
    horizon_end: date
    days_count: int
    stockout_date: date | None  # первая дата нулевого остатка (closing_stock == 0)
    first_deficit_date: date | None  # первая дата с daily_deficit > 0
    total_incoming: Decimal  # сумма поступившего за горизонт
    total_consumption: Decimal  # сумма списанного расхода за горизонт
    total_expired: Decimal  # сумма списанной просрочки за горизонт
    total_deficit: Decimal  # сумма дефицита за горизонт
    has_temporary_stockout: bool  # возникновение дефицита до поставки


@dataclass(frozen=True)
class IncomingOrderSnapshot:
    """Снимок ожидаемой неполученной поставки."""

    order_id: int
    doc_number: str
    expected_date: date
    pending_qty: Decimal
    unit_price: Decimal | None = None


@dataclass(frozen=True)
class ProcurementContext:
    """Закупочные условия и ожидаемые поставки для товара."""

    supplier_id: str | None
    supplier_name: str | None
    lead_time_days: int | None
    package_size: Decimal | None
    min_order_qty: Decimal | None
    unit_price: Decimal | None
    price_source: str | None  # "receipt", "estimated" или None
    pending_orders: tuple[IncomingOrderSnapshot, ...] = ()
    delayed_orders: tuple[IncomingOrderSnapshot, ...] = ()


@dataclass(frozen=True)
class OrderRecommendation:
    """Рекомендация по заказу и расчётные показатели потребности."""

    forecast_consumption: Decimal  # a * D
    safety_stock: Decimal  # a * S
    reorder_point: Decimal | None  # a * (L + S) или None
    stockout_date: date | None  # дата исчерпания запаса
    order_date: date | None  # рекомендуемая дата заказа
    recommended_qty: Decimal  # объём с учётом min_order и упаковки
    unit_price: Decimal | None  # цена за единицу (2 знака)
    total_cost: Decimal | None  # общая оценочная стоимость (2 знака)
    warnings: tuple[str, ...] = ()
    explanation_details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExplanationItem:
    """Элемент исходных данных в explanation.data_used."""

    name: str
    value: Any
    source: str


@dataclass(frozen=True)
class ForecastExplanation:
    """Структурированное объяснение прогноза."""

    data_used: tuple[ExplanationItem, ...] = ()
    formulas: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ForecastResult:
    """Полный результат расчёта прогноза потребности."""

    sku: str
    location: str
    as_of: date
    horizon_start: date
    horizon_end: date
    days_count: int
    consumption_metrics: ConsumptionMetrics
    daily_fefo: DailyFefoResult
    order_recommendation: OrderRecommendation
    current_stock: Decimal
    available_stock: Decimal
    incoming_qty: Decimal
    explanation: ForecastExplanation
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertItem:
    """Элемент предупреждения по рискам запасов и ограничениям данных."""

    id: str
    type: str  # stockout, potential_stockout, expiring_soon, expired...
    level: str  # critical, warning, info

    sku: str
    location: str
    batch_id: int | None
    message: str
    metrics: dict[str, Any]
    as_of: date
