"""Чистые модульные тесты дневного планирования пары с месячной целью пополнения."""

from datetime import date, datetime
from decimal import Decimal

from app.inventory.domain import BatchSnapshot
from app.procurement_plan.dates import add_one_month, compute_coverage_interval
from app.procurement_plan.planning import plan_pair_procurement


def test_add_one_month_and_coverage_interval() -> None:
    """Проверка календарного прибавления одного месяца и интервала покрытия."""
    assert add_one_month(date(2026, 1, 31)) == date(2026, 2, 28)
    assert add_one_month(date(2024, 1, 31)) == date(2024, 2, 29)
    assert add_one_month(date(2026, 8, 31)) == date(2026, 9, 30)
    assert add_one_month(date(2026, 9, 15)) == date(2026, 10, 15)

    start, end = compute_coverage_interval(date(2026, 9, 15), date(2026, 10, 1))
    assert start == date(2026, 9, 15)
    assert end == date(2026, 10, 1)


def test_two_orders_over_three_months_horizon() -> None:
    """Проверка генерации двух последовательных заказов за трёхмесячный горизонт."""
    as_of = date(2026, 9, 1)
    consumption = Decimal("10.000000")
    lead_time = 5

    batch = BatchSnapshot(
        id=1,
        item_id=1,
        location_id=1,
        batch_number="B-INIT",
        receipt_doc_number="DOC-INIT",
        unit_price=Decimal("50.00"),
        receipt_date=date(2026, 8, 20),
        expiry_date=None,
        created_at=datetime(2026, 8, 20, 10, 0),
    )
    stocks = {1: Decimal("100.000")}

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=3,
        service_days=0,
        sku="SKU-TEST-1",
        category="Категория 1",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[batch],
        batch_stocks=stocks,
        lead_time_days=lead_time,
        package_size=Decimal("10.000"),
        min_order_qty=Decimal("50.000"),
        unit_price=Decimal("120.00"),
        price_source="receipt",
        supplier_id="SUP-1",
        supplier_name="Поставщик 1",
    )

    assert len(res.items) >= 2
    order1 = res.items[0]
    order2 = res.items[1]

    assert order1.order_date == date(2026, 9, 6)
    assert order1.delivery_date == date(2026, 9, 11)
    assert order1.coverage_start == date(2026, 9, 11)
    assert order1.coverage_end == date(2026, 10, 11)
    assert order1.quantity == Decimal("300.000")
    assert order1.unit_price == Decimal("120.00")
    assert order1.total_cost == Decimal("36000.00")

    assert order2.order_date == date(2026, 10, 6)
    assert order2.delivery_date == date(2026, 10, 11)
    assert order2.coverage_start == date(2026, 10, 11)
    assert order2.coverage_end == date(2026, 11, 11)
    assert order2.quantity == Decimal("310.000")

    assert order2.order_date > order1.order_date
    assert order2.delivery_date > order1.delivery_date
    assert order2.coverage_start >= order1.coverage_end


def test_early_deficit_and_lead_time_clamp() -> None:
    """Проверка заказа на as_of при раннем дефиците и срока поставки."""
    as_of = date(2026, 9, 15)
    consumption = Decimal("10.000000")
    lead_time = 7

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-ZERO",
        category="Бакалея",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[],
        batch_stocks={},
        lead_time_days=lead_time,
        unit_price=Decimal("10.00"),
    )

    assert len(res.items) == 1
    item = res.items[0]
    assert item.order_date == as_of
    assert item.delivery_date == date(2026, 9, 22)
    assert item.coverage_start == date(2026, 9, 22)
    assert item.coverage_end == date(2026, 10, 15)
    assert any("Потребность возникает раньше возможного поступления" in w for w in item.warnings)
    assert any("Потребность возникает раньше возможного поступления" in w for w in res.warnings)


def test_service_days_increases_need_and_shifts_order() -> None:
    """Проверка страхового запаса: заказ срабатывает раньше и включает страховку."""
    as_of = date(2026, 9, 1)
    consumption = Decimal("10.000000")
    lead_time = 4

    batch = BatchSnapshot(
        id=1,
        item_id=1,
        location_id=1,
        batch_number="B-1",
        receipt_doc_number="DOC-1",
        unit_price=Decimal("10.00"),
        receipt_date=date(2026, 8, 20),
        expiry_date=None,
        created_at=datetime(2026, 8, 20, 10, 0),
    )
    stocks = {1: Decimal("100.000")}

    res_s0 = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-S",
        category="Тест",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[batch],
        batch_stocks=stocks,
        lead_time_days=lead_time,
    )
    assert res_s0.items[0].order_date == date(2026, 9, 7)

    res_s5 = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=5,
        sku="SKU-S",
        category="Тест",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[batch],
        batch_stocks=stocks,
        lead_time_days=lead_time,
    )
    assert res_s5.items[0].order_date < res_s0.items[0].order_date
    assert res_s5.items[0].quantity > res_s0.items[0].quantity


def test_rounding_min_order_and_package_size() -> None:
    """Проверка соблюдения кратности упаковки и минимального заказа."""
    as_of = date(2026, 9, 1)
    consumption = Decimal("7.000000")
    lead_time = 2

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-ROUND",
        category="Тест",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[],
        batch_stocks={},
        lead_time_days=lead_time,
        min_order_qty=Decimal("500.000"),
        package_size=Decimal("50.000"),
    )

    assert len(res.items) == 1
    item = res.items[0]
    assert item.raw_quantity < Decimal("500.000")
    assert item.quantity == Decimal("500.000")
    assert item.quantity % Decimal("50.000") == Decimal("0.000")
