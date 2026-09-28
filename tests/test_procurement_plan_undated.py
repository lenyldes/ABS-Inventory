"""Чистые тесты недатированных позиций, отсутствия цены и неполной истории (подзадача 2.3)."""

from datetime import date, datetime
from decimal import Decimal

from app.forecasting.domain import IncomingOrderSnapshot, ProcurementContext
from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.models.catalog import Item, Location
from app.procurement_plan.domain import PlanItemLocationPair
from app.procurement_plan.planning import plan_pair_procurement
from app.procurement_plan.snapshot_adapter import plan_pair_from_snapshot
from app.procurement_plan.warnings import (
    WARN_INCOMPLETE_HISTORY,
    WARN_LEAD_TIME_UNKNOWN,
    WARN_NO_DEMAND_HISTORY,
    WARN_PRICE_UNKNOWN,
)


def test_missing_lead_time_generates_undated_item_and_warning() -> None:
    """Отсутствие срока поставки: формируется недатированная позиция на весь горизонт."""
    as_of = date(2026, 9, 15)
    consumption = Decimal("4.000000")

    # 1. Горизонт 3 месяца: 91 день * 4 = 364.000, кратность 10 -> 370.000
    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=3,
        service_days=0,
        sku="SKU-UNDATED",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=consumption,
        lead_time_days=None,
        package_size=Decimal("10.000"),
        min_order_qty=Decimal("50.000"),
        unit_price=Decimal("200.00"),
    )

    assert len(res.items) == 1
    item = res.items[0]
    assert item.is_undated is True
    assert item.order_date is None
    assert item.delivery_date is None
    assert item.expected_date is None
    assert item.coverage_start is None
    assert item.coverage_end is None

    assert item.raw_quantity == Decimal("364.000")
    assert item.quantity == Decimal("370.000")
    assert item.unit_price == Decimal("200.00")
    assert item.total_cost == Decimal("74000.00")

    assert any("LEAD_TIME_UNKNOWN" in w for w in item.warnings)
    assert any("LEAD_TIME_UNKNOWN" in w for w in res.warnings)
    assert any(WARN_LEAD_TIME_UNKNOWN in w for w in item.warnings)

    # 2. Горизонт 1 месяц: 30 дней * 4 = 120.000
    res_1m = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-UNDATED",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=consumption,
        lead_time_days=None,
        package_size=Decimal("10.000"),
        min_order_qty=Decimal("50.000"),
        unit_price=Decimal("200.00"),
    )
    assert len(res_1m.items) == 1
    item_1m = res_1m.items[0]
    assert item_1m.raw_quantity == Decimal("120.000")
    assert item_1m.quantity == Decimal("120.000")
    assert item_1m.total_cost == Decimal("24000.00")


def test_missing_price_retains_quantity_and_nulls_cost() -> None:
    """Отсутствие цены: unit_price=None, total_cost=None, предупреждение PRICE_UNKNOWN."""
    as_of = date(2026, 9, 1)
    consumption = Decimal("5.000000")
    lead_time = 3

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-NOPRICE",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=consumption,
        lead_time_days=lead_time,
        unit_price=None,
    )

    assert len(res.items) >= 1
    item = res.items[0]
    assert item.quantity > Decimal("0.000")
    assert item.order_date is not None
    assert item.delivery_date is not None
    assert item.unit_price is None
    assert item.total_cost is None
    assert any("PRICE_UNKNOWN" in w for w in item.warnings)
    assert any("PRICE_UNKNOWN" in w for w in res.warnings)
    assert any(WARN_PRICE_UNKNOWN in w for w in item.warnings)


def test_zero_consumption_gives_no_demand_history() -> None:
    """Нулевой расход: нет заказов и выдаётся предупреждение NO_DEMAND_HISTORY."""
    as_of = date(2026, 9, 1)
    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-NODEMAND",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=Decimal("0.000000"),
        lead_time_days=None,
    )

    assert len(res.items) == 0
    assert any("NO_DEMAND_HISTORY" in w for w in res.warnings)
    assert any(WARN_NO_DEMAND_HISTORY in w for w in res.warnings)


def test_snapshot_adapter_incomplete_history_warning() -> None:
    """Адаптер снимка БД возвращает предупреждение INCOMPLETE_HISTORY при истории < 90 дней."""
    as_of = date(2026, 9, 15)
    item = Item(id=10, sku="SKU-INC", name="Тест неполная", category="Категория", unit="шт")
    location = Location(id=10, code="LOC-MSK", name="Москва")

    movement = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 5),
        item_id=10,
        location_id=10,
        batch_id=1,
        type="consume",
        quantity=Decimal("10.000"),
        doc_number="DOC-INC-1",
        status="active",
        parent_movement_id=None,
    )
    batch = BatchSnapshot(
        id=1,
        item_id=10,
        location_id=10,
        batch_number="B-INC",
        receipt_doc_number="DOC-REC",
        unit_price=Decimal("100.00"),
        receipt_date=date(2026, 9, 5),
        expiry_date=None,
        created_at=datetime(2026, 9, 5, 10, 0),
    )
    ctx = ProcurementContext(
        supplier_id="SUP-1",
        supplier_name="Поставщик",
        lead_time_days=3,
        package_size=None,
        min_order_qty=None,
        unit_price=Decimal("100.00"),
        price_source="receipt",
    )

    pair = PlanItemLocationPair(
        item=item,
        location=location,
        batches=(batch,),
        movements=(movement,),
        procurement_context=ctx,
        active_orders=(),
    )

    res = plan_pair_from_snapshot(
        pair=pair,
        as_of=as_of,
        horizon_months=1,
        service_days=0,
    )

    assert any("INCOMPLETE_HISTORY" in w for w in res.warnings)
    assert any(WARN_INCOMPLETE_HISTORY in w for w in res.warnings)


def test_missing_lead_time_accounts_for_existing_incoming_orders() -> None:
    """Недатированная позиция уменьшает объём на оформленные поставки в горизонте."""
    as_of = date(2026, 9, 15)
    consumption = Decimal("5.000000")
    # Горизонт 1 месяц: 30 дней (16.09 - 15.10). Потребность = 150.000
    # Текущий остаток = 20.000
    # Действующий заказ внутри горизонта (25.09) на 50.000
    # Заказ вне горизонта (20.10) на 100.000 -> не должен учитываться
    batch = BatchSnapshot(
        id=1,
        item_id=1,
        location_id=1,
        batch_number="B-1",
        receipt_doc_number="DOC-1",
        unit_price=Decimal("100.00"),
        receipt_date=date(2026, 9, 1),
        expiry_date=None,
    )
    order_in = IncomingOrderSnapshot(
        order_id=10,
        doc_number="PO-IN",
        expected_date=date(2026, 9, 25),
        pending_qty=Decimal("50.000"),
        unit_price=Decimal("100.00"),
    )
    order_out = IncomingOrderSnapshot(
        order_id=11,
        doc_number="PO-OUT",
        expected_date=date(2026, 10, 20),
        pending_qty=Decimal("100.000"),
        unit_price=Decimal("100.00"),
    )

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-UNDATED-ORDERS",
        category="Категория",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[batch],
        batch_stocks={1: Decimal("20.000")},
        incoming_orders=[order_in, order_out],
        lead_time_days=None,
        package_size=Decimal("10.000"),
        unit_price=Decimal("100.00"),
    )

    assert len(res.items) == 1
    item = res.items[0]
    assert item.is_undated is True
    # Потребность: 150 - 20 (склад) - 50 (заказ в горизонте) = 80.000
    assert item.raw_quantity == Decimal("80.000")
    assert item.quantity == Decimal("80.000")
    assert item.total_cost == Decimal("8000.00")
    assert item.metrics["usable_stock"] == "70.000"
