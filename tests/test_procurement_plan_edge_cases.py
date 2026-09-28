"""Чистые тесты обработки задержанных заказов, дефицита и горизонта (подзадача 2.3)."""

from datetime import date
from decimal import Decimal

from app.forecasting.domain import IncomingOrderSnapshot
from app.procurement_plan.planning import plan_pair_procurement
from app.procurement_plan.warnings import WARN_ORDER_DELAYED


def test_delayed_orders_arrive_as_of_and_emit_warning() -> None:
    """Задержанный заказ (expected_date <= as_of) исключается из покрытия и даёт ORDER_DELAYED."""
    as_of = date(2026, 9, 15)
    consumption = Decimal("10.000000")
    lead_time = 5

    delayed = IncomingOrderSnapshot(
        order_id=1,
        doc_number="PO-DELAYED-1",
        expected_date=date(2026, 9, 10),
        pending_qty=Decimal("50.000"),
        unit_price=Decimal("100.00"),
    )

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-DELAYED",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[],
        batch_stocks={},
        incoming_orders=[delayed],
        lead_time_days=lead_time,
        unit_price=Decimal("100.00"),
    )

    assert any("ORDER_DELAYED" in w for w in res.warnings)
    assert any(WARN_ORDER_DELAYED in w for w in res.warnings)
    assert len(res.items) >= 1
    assert res.items[0].order_date == date(2026, 9, 15)
    assert res.items[0].delivery_date == date(2026, 9, 20)
    # Задержанный заказ 50 ед. исключен из покрытия; поступление 20.09 покрывает 26 дней до 15.10:
    assert res.items[0].quantity == Decimal("260.000")
    assert any("ORDER_DELAYED" in w for w in res.items[0].warnings)


def test_partially_received_order_uses_only_pending_qty() -> None:
    """Частично полученный заказ учитывает только pending_qty."""
    as_of = date(2026, 9, 1)
    consumption = Decimal("10.000000")
    lead_time = 4

    partial_order = IncomingOrderSnapshot(
        order_id=2,
        doc_number="PO-PARTIAL-1",
        expected_date=date(2026, 9, 3),
        pending_qty=Decimal("20.000"),
        unit_price=Decimal("150.00"),
    )

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-PARTIAL",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[],
        batch_stocks={},
        incoming_orders=[partial_order],
        lead_time_days=lead_time,
        unit_price=Decimal("150.00"),
    )

    assert len(res.items) >= 1
    assert res.items[0].order_date == as_of


def test_temporary_deficit_orders_on_as_of_with_warning() -> None:
    """Временный дефицит: запас исчерпан до даты поставки -> заказ на as_of с TEMPORARY_DEFICIT."""
    as_of = date(2026, 9, 10)
    consumption = Decimal("10.000000")
    lead_time = 7

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-DEFICIT",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[],
        batch_stocks={},
        lead_time_days=lead_time,
        unit_price=Decimal("80.00"),
    )

    assert len(res.items) >= 1
    item = res.items[0]
    assert item.order_date == as_of
    assert item.delivery_date == date(2026, 9, 17)
    assert any("TEMPORARY_DEFICIT" in w for w in item.warnings)
    assert any("TEMPORARY_DEFICIT" in w for w in res.warnings)
    # Проверка конкретных дат интервала дефицита в тексте предупреждения
    assert any("2026-09-11" in w and "2026-09-17" in w for w in item.warnings)
    assert any("2026-09-11" in w and "2026-09-17" in w for w in res.warnings)
    # Проверка параметров интервала дефицита в метриках позиции
    assert item.metrics["deficit_start"] == "2026-09-11"
    assert item.metrics["deficit_end"] == "2026-09-16"
    assert item.metrics["deficit_delivery_date"] == "2026-09-17"


def test_delivery_beyond_horizon_no_order_placed() -> None:
    """Поставка за горизонтом: заказ в рамках горизонта не размещается."""
    as_of = date(2026, 9, 15)
    consumption = Decimal("10.000000")
    lead_time = 60

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-FAR",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=consumption,
        lead_time_days=lead_time,
    )

    assert len(res.items) == 0
    assert any("DELIVERY_BEYOND_HORIZON" in w for w in res.warnings)
    assert any("позднее конца горизонта" in w for w in res.warnings)
