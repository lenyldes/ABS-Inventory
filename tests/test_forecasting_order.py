"""Тесты модуля расчёта заказа и потребности (задача 2.2)."""

from datetime import date
from decimal import Decimal

from app.forecasting.domain import DailyFefoResult, DailyForecastStep
from app.forecasting.order_calculation import calculate_order_recommendation


def _create_mock_fefo(
    as_of: date,
    steps_data: list[tuple[date, Decimal, Decimal, Decimal, Decimal, Decimal]],
) -> DailyFefoResult:
    """Вспомогательная функция для создания DailyFefoResult в тестах."""
    steps = tuple(
        DailyForecastStep(
            date=d,
            consumption=c,
            incoming=inc,
            expired=exp,
            closing_stock=cls,
            daily_deficit=defic,
        )
        for d, c, inc, exp, cls, defic in steps_data
    )
    first_stockout = next((s.date for s in steps if s.closing_stock <= Decimal("0.000")), None)
    first_defic = next((s.date for s in steps if s.daily_deficit > Decimal("0.000")), None)
    tot_inc = sum((s.incoming for s in steps), Decimal("0.000"))
    tot_cons = sum((s.consumption for s in steps), Decimal("0.000"))
    tot_exp = sum((s.expired for s in steps), Decimal("0.000"))
    tot_def = sum((s.daily_deficit for s in steps), Decimal("0.000"))

    return DailyFefoResult(
        daily_steps=steps,
        horizon_start=steps[0].date if steps else as_of,
        horizon_end=steps[-1].date if steps else as_of,
        days_count=len(steps),
        stockout_date=first_stockout,
        first_deficit_date=first_defic,
        total_incoming=tot_inc,
        total_consumption=tot_cons,
        total_expired=tot_exp,
        total_deficit=tot_def,
        has_temporary_stockout=tot_def > Decimal("0") and tot_inc > Decimal("0"),
    )


def test_reorder_point_and_safety_stock() -> None:
    """Проверка точки заказа и страхового запаса (a=2, L=7, S=3)."""
    as_of = date(2026, 9, 28)
    rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("2.000000"),
        days_count=10,
        service_days=3,
        lead_time_days=7,
        unit_price=Decimal("100.00"),
        available_stock=Decimal("20.000"),
    )
    assert rec.safety_stock == Decimal("6.000")
    assert rec.reorder_point == Decimal("20.000")
    assert rec.forecast_consumption == Decimal("20.000")


def test_packaging_and_min_order() -> None:
    """Минимум 10 не кратен упаковке 3 при потребности 7 -> рекомендуются 12."""
    as_of = date(2026, 9, 28)
    # Потребность: forecast (10) + safety (0) - stock (3) = 7
    rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("1.000000"),
        days_count=10,
        service_days=0,
        lead_time_days=3,
        package_size=Decimal("3.000"),
        min_order_qty=Decimal("10.000"),
        available_stock=Decimal("3.000"),
    )
    assert rec.recommended_qty == Decimal("12.000")


def test_sufficient_stock_zero_recommendation() -> None:
    """При достаточном остатке закупка равна 0 независимо от минимума."""
    as_of = date(2026, 9, 28)
    rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("1.000000"),
        days_count=5,
        service_days=0,
        lead_time_days=3,
        package_size=Decimal("10.000"),
        min_order_qty=Decimal("50.000"),
        available_stock=Decimal("20.000"),
    )
    assert rec.recommended_qty == Decimal("0.000")


def test_price_rounding_scenario() -> None:
    """Округление цены 10.555 до 10.56 и стоимости: 7 * 10.56 = 73.92."""
    as_of = date(2026, 9, 28)
    rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("1.000000"),
        days_count=7,
        service_days=0,
        lead_time_days=2,
        package_size=Decimal("1.000"),
        unit_price=Decimal("10.555"),
        available_stock=Decimal("0.000"),
    )
    assert rec.recommended_qty == Decimal("7.000")
    assert rec.unit_price == Decimal("10.56")
    assert rec.total_cost == Decimal("73.92")


def test_zero_consumption_behavior() -> None:
    """При нулевом расходе: order_date=None, stockout_date=None, recommended=0."""
    as_of = date(2026, 9, 28)
    rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("0.000000"),
        days_count=14,
        service_days=3,
        lead_time_days=5,
        unit_price=Decimal("50.00"),
        available_stock=Decimal("10.000"),
    )
    assert rec.recommended_qty == Decimal("0.000")
    assert rec.stockout_date is None
    assert rec.order_date is None
    assert rec.forecast_consumption == Decimal("0.000")
    assert any("Потребление за 90 дней отсутствует" in w for w in rec.warnings)


def test_zero_safety_stock_sufficient_inventory() -> None:
    """При S = 0 и достаточном запасе stockout_date и order_date равны None."""
    as_of = date(2026, 9, 28)
    # Остатка 10 хватает на 5 дней по 2 ед./день
    d0, d2 = Decimal("0"), Decimal("2")
    fefo = _create_mock_fefo(
        as_of,
        [
            (date(2026, 9, 29), d2, d0, d0, Decimal("8"), d0),
            (date(2026, 9, 30), d2, d0, d0, Decimal("6"), d0),
            (date(2026, 10, 1), d2, d0, d0, Decimal("4"), d0),
            (date(2026, 10, 2), d2, d0, d0, Decimal("2"), d0),
            (date(2026, 10, 3), d2, d0, d0, Decimal("1"), d0),
        ],
    )
    rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("2.000000"),
        days_count=5,
        service_days=0,
        lead_time_days=2,
        available_stock=Decimal("10.000"),
        daily_fefo=fefo,
    )
    assert rec.stockout_date is None
    assert rec.order_date is None
    assert rec.recommended_qty == Decimal("0.000")


def test_order_date_past_due_immediate_recommendation() -> None:
    """Если дата заказа <= as_of, заказ рекомендуется немедленно на as_of."""
    as_of = date(2026, 10, 1)
    d0, d2 = Decimal("0"), Decimal("2")
    # Потребность падает до нуля 04.10, L = 4 дня -> 04.10 - 4 = 30.09 <= 01.10
    fefo = _create_mock_fefo(
        as_of,
        [
            (date(2026, 10, 2), d2, d0, d0, Decimal("4"), d0),
            (date(2026, 10, 3), d2, d0, d0, Decimal("2"), d0),
            (date(2026, 10, 4), d2, d0, d0, Decimal("0"), d0),
            (date(2026, 10, 5), d0, d0, d0, Decimal("0"), d2),
        ],
    )
    rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("2.000000"),
        days_count=4,
        service_days=0,
        lead_time_days=4,
        available_stock=Decimal("6.000"),
        daily_fefo=fefo,
    )
    assert rec.stockout_date == date(2026, 10, 4)
    assert rec.order_date == as_of
    assert any("немедленный заказ" in w for w in rec.warnings)


def test_missing_lead_time_and_price() -> None:
    """При отсутствии срока поставки и цены поля равны None с предупреждениями."""
    as_of = date(2026, 9, 28)
    rec = calculate_order_recommendation(
        as_of=as_of,
        average_daily_consumption=Decimal("3.000000"),
        days_count=5,
        service_days=1,
        lead_time_days=None,
        unit_price=None,
        available_stock=Decimal("5.000"),
    )
    assert rec.reorder_point is None
    assert rec.order_date is None
    assert rec.unit_price is None
    assert rec.total_cost is None
    assert rec.recommended_qty > Decimal("0.000")
    assert any("Срок поставки не задан" in w for w in rec.warnings)
    assert any("Цена не указана" in w for w in rec.warnings)
