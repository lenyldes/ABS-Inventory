"""Граничные тесты чистых календарных и суточных расчётов FEFO (задача 2.1)."""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.api.forecast_schemas import DailyForecastItem
from app.forecasting.daily_fefo import simulate_daily_fefo
from app.forecasting.domain import IncomingOrderSnapshot
from app.forecasting.order_calculation import calculate_order_recommendation
from app.inventory.domain import BatchSnapshot


def _make_batch(
    batch_id: int,
    receipt_date: date,
    expiry_date: date | None,
) -> BatchSnapshot:
    """Вспомогательная фабрика учётных партий для тестов."""
    return BatchSnapshot(
        id=batch_id,
        item_id=1,
        location_id=1,
        batch_number=f"B-{batch_id}",
        receipt_date=receipt_date,
        expiry_date=expiry_date,
        unit_price=Decimal("100.00"),
        receipt_doc_number=f"DOC-{batch_id}",
    )


def test_month_boundary_horizon_leap_and_non_leap() -> None:
    """Проверка границ горизонта на стыке месяцев в високосный и невисокосный годы."""
    # Невисокосный год: 31.01.2025 -> февраль (28 дней)
    res_non_leap = simulate_daily_fefo(
        as_of=date(2025, 1, 31),
        average_daily_consumption=Decimal("1.000"),
        batches=[],
        horizon_months=1,
    )
    assert res_non_leap.horizon_start == date(2025, 2, 1)
    assert res_non_leap.horizon_end == date(2025, 2, 28)
    assert res_non_leap.days_count == 28
    assert len(res_non_leap.daily_steps) == 28

    # Високосный год: 31.01.2024 -> февраль (29 дней)
    res_leap = simulate_daily_fefo(
        as_of=date(2024, 1, 31),
        average_daily_consumption=Decimal("1.000"),
        batches=[],
        horizon_months=1,
    )
    assert res_leap.horizon_start == date(2024, 2, 1)
    assert res_leap.horizon_end == date(2024, 2, 29)
    assert res_leap.days_count == 29
    assert len(res_leap.daily_steps) == 29


def test_zero_consumption_behavior() -> None:
    """При нулевом расходе stockout_date равен None, остаток не списывается в расход."""
    as_of = date(2026, 10, 1)
    b = _make_batch(1, date(2026, 9, 1), date(2026, 10, 10))
    res = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("0.000"),
        batches=[b],
        batch_stocks={1: Decimal("5.000")},
        horizon_days=5,
    )
    assert res.stockout_date is None
    assert res.first_deficit_date is None
    assert res.total_consumption == Decimal("0.000")
    assert res.total_deficit == Decimal("0.000")
    assert res.has_temporary_stockout is False
    assert all(s.closing_stock == Decimal("5.000") for s in res.daily_steps)


def test_delayed_incoming_orders_ignored() -> None:
    """Поставки с expected_date <= as_of считаются задержанными и не учитываются."""
    as_of = date(2026, 10, 1)
    delayed = [
        IncomingOrderSnapshot(
            order_id=1,
            doc_number="PO-OLD",
            expected_date=date(2026, 10, 1),
            pending_qty=Decimal("10.000"),
        )
    ]
    res = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("1.000"),
        batches=[],
        incoming_orders=delayed,
        horizon_days=2,
    )
    assert res.total_incoming == Decimal("0.000")
    assert res.first_deficit_date == date(2026, 10, 2)


def test_negative_consumption_raises_error() -> None:
    """Отрицательный среднесуточный расход недопустим."""
    with pytest.raises(ValueError, match="не может быть отрицательным"):
        simulate_daily_fefo(
            as_of=date(2026, 10, 1),
            average_daily_consumption=Decimal("-1.000"),
            batches=[],
            horizon_days=3,
        )


def test_small_daily_consumption_retains_precision_until_response() -> None:
    """Малый расход не исчезает при моделировании и совпадает с прогнозом за горизонт."""
    as_of = date(2026, 10, 1)
    daily_average = Decimal("0.000400")
    result = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=daily_average,
        batches=[],
        horizon_days=5,
    )
    recommendation = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=daily_average,
        days_count=5,
        daily_fefo=result,
    )

    assert result.first_deficit_date == date(2026, 10, 2)
    assert all(step.daily_deficit == daily_average for step in result.daily_steps)
    assert result.total_deficit == recommendation.forecast_consumption == Decimal("0.002")

    first_day = DailyForecastItem(**vars(result.daily_steps[0]))
    serialized = json.loads(first_day.model_dump_json())
    assert serialized["daily_deficit"] == "0.000"
    assert first_day.daily_deficit == daily_average


def test_small_consumption_uses_precise_stock_for_order_date() -> None:
    """Округлённый дневной остаток не сдвигает дату исчерпания и заказа."""
    as_of = date(2026, 10, 1)
    batch = _make_batch(1, date(2026, 9, 1), None)
    result = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("0.000400"),
        batches=[batch],
        batch_stocks={1: Decimal("0.001")},
        horizon_days=3,
    )
    recommendation = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("0.000400"),
        days_count=3,
        lead_time_days=1,
        daily_fefo=result,
        available_stock=Decimal("0.001"),
    )

    assert result.daily_steps[1].closing_stock == Decimal("0.000200")
    assert result.stockout_date == date(2026, 10, 4)
    assert result.first_deficit_date == date(2026, 10, 4)
    assert recommendation.stockout_date == date(2026, 10, 4)
    assert recommendation.order_date == date(2026, 10, 3)


def test_small_safety_stock_uses_precise_threshold_and_need() -> None:
    """Страховой запас ниже 0,001 участвует в дате и объёме заказа."""
    as_of = date(2026, 10, 1)
    batch = _make_batch(1, date(2026, 9, 1), None)
    result = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("0.000400"),
        batches=[batch],
        batch_stocks={1: Decimal("0.001")},
        horizon_days=3,
    )
    recommendation = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("0.000400"),
        days_count=3,
        service_days=1,
        lead_time_days=0,
        daily_fefo=result,
        available_stock=Decimal("0.001"),
    )

    assert recommendation.safety_stock == Decimal("0.000")
    assert recommendation.order_date == date(2026, 10, 3)
    assert recommendation.recommended_qty == Decimal("0.001")
