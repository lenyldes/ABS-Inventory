"""Чистые модульные тесты влияния FEFO, ожидаемых заказов и снимка БД на план."""

from datetime import date, datetime
from decimal import Decimal

from app.api.plan_schemas import ExistingOrderSnapshotSchema
from app.forecasting.domain import IncomingOrderSnapshot, ProcurementContext
from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.models.catalog import Item, Location
from app.procurement_plan.domain import PlanItemLocationPair
from app.procurement_plan.planning import plan_pair_procurement
from app.procurement_plan.snapshot_adapter import plan_pair_from_snapshot


def test_fefo_expiry_triggers_earlier_order() -> None:
    """Проверка влияния срока годности FEFO: сгорание остатка ускоряет следующий заказ."""
    as_of = date(2026, 9, 1)
    consumption = Decimal("5.000000")
    lead_time = 3

    batch_exp = BatchSnapshot(
        id=1,
        item_id=1,
        location_id=1,
        batch_number="B-EXP",
        receipt_doc_number="DOC-EXP",
        unit_price=Decimal("100.00"),
        receipt_date=date(2026, 8, 20),
        expiry_date=date(2026, 9, 9),
        created_at=datetime(2026, 8, 20, 10, 0),
    )

    res_exp = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-EXP",
        category="Скоропорт",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[batch_exp],
        batch_stocks={1: Decimal("50.000")},
        lead_time_days=lead_time,
        unit_price=Decimal("100.00"),
    )

    assert len(res_exp.items) >= 1
    assert res_exp.items[0].order_date == date(2026, 9, 7)
    assert res_exp.items[0].delivery_date == date(2026, 9, 10)

    batch_no_exp = BatchSnapshot(
        id=2,
        item_id=1,
        location_id=1,
        batch_number="B-NOEXP",
        receipt_doc_number="DOC-NOEXP",
        unit_price=Decimal("100.00"),
        receipt_date=date(2026, 8, 20),
        expiry_date=None,
        created_at=datetime(2026, 8, 20, 10, 0),
    )
    res_no_exp = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-EXP",
        category="Скоропорт",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[batch_no_exp],
        batch_stocks={2: Decimal("50.000")},
        lead_time_days=lead_time,
        unit_price=Decimal("100.00"),
    )
    assert res_no_exp.items[0].order_date == date(2026, 9, 8)
    assert res_no_exp.items[0].delivery_date == date(2026, 9, 11)
    assert res_exp.items[0].order_date < res_no_exp.items[0].order_date


def test_existing_order_prevents_duplicate_procurement() -> None:
    """Проверка исключения дублирования объёма при наличии ожидаемого заказа."""
    as_of = date(2026, 9, 1)
    consumption = Decimal("10.000000")
    lead_time = 5

    incoming = [
        IncomingOrderSnapshot(
            order_id=101,
            doc_number="PO-EXIST-1",
            expected_date=date(2026, 9, 6),
            pending_qty=Decimal("400.000"),
            unit_price=Decimal("100.00"),
        )
    ]

    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-EXIST",
        category="Тест",
        location="LOC-1",
        average_daily_consumption=consumption,
        batches=[],
        batch_stocks={},
        incoming_orders=incoming,
        lead_time_days=lead_time,
    )
    assert len(res.items) == 0


def test_zero_consumption_and_missing_lead_time() -> None:
    """Проверка краевых случаев: нулевой расход и отсутствие срока поставки."""
    as_of = date(2026, 9, 1)

    # 1. Нулевой расход
    res_zero = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-Z",
        category="Тест",
        location="LOC-1",
        average_daily_consumption=Decimal("0.000000"),
        lead_time_days=5,
    )
    assert len(res_zero.items) == 0
    assert any("Потребление за 90 дней отсутствует" in w for w in res_zero.warnings)

    # 2. Неизвестный срок поставки
    res_no_lead = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,
        service_days=0,
        sku="SKU-NL",
        category="Тест",
        location="LOC-1",
        average_daily_consumption=Decimal("5.000000"),
        lead_time_days=None,
    )
    assert len(res_no_lead.items) == 1
    assert res_no_lead.items[0].is_undated is True
    assert res_no_lead.items[0].order_date is None
    assert any("Срок поставки не задан" in w for w in res_no_lead.warnings)


def test_delivery_beyond_horizon_warning() -> None:
    """Проверка предупреждения при невозможности поставки до конца горизонта."""
    as_of = date(2026, 9, 15)
    res = plan_pair_procurement(
        as_of=as_of,
        horizon_months=1,  # конец 15.10.2026
        service_days=0,
        sku="SKU-LATE",
        category="Тест",
        location="LOC-1",
        average_daily_consumption=Decimal("10.000000"),
        lead_time_days=40,  # поставка 25.10.2026 > 15.10.2026
    )
    assert len(res.items) == 0
    assert any("позднее конца горизонта" in w for w in res.warnings)


def test_plan_pair_from_snapshot_integration() -> None:
    """Проверка вызова адаптера плана пары через структуру PlanItemLocationPair."""
    as_of = date(2026, 9, 15)
    item = Item(id=1, sku="SKU-SNAP", name="Товар", category="Косметика", unit="шт")
    location = Location(id=1, code="LOC-MSK", name="Москва")

    # Движение расхода: 90 шт за 90 дней -> расход 1.000000 шт/день
    movement = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 10),
        item_id=1,
        location_id=1,
        batch_id=1,
        type="consume",
        quantity=Decimal("90.000"),
        doc_number="DOC-M1",
        status="active",
        parent_movement_id=None,
    )
    batch = BatchSnapshot(
        id=1,
        item_id=1,
        location_id=1,
        batch_number="B-1",
        receipt_doc_number="DOC-1",
        unit_price=Decimal("100.00"),
        receipt_date=date(2026, 8, 1),
        expiry_date=None,
    )

    ctx = ProcurementContext(
        supplier_id="SUP-1",
        supplier_name="Тест",
        lead_time_days=3,
        package_size=Decimal("10.000"),
        min_order_qty=Decimal("20.000"),
        unit_price=Decimal("150.00"),
        price_source="receipt",
    )
    orders = (
        ExistingOrderSnapshotSchema(
            order_id=1,
            doc_number="PO-1",
            sku="SKU-SNAP",
            location="LOC-MSK",
            expected_date=date(2026, 9, 20),
            pending_qty=Decimal("10.000"),
        ),
    )

    pair = PlanItemLocationPair(
        item=item,
        location=location,
        batches=(batch,),
        movements=(movement,),
        procurement_context=ctx,
        active_orders=orders,
    )

    result = plan_pair_from_snapshot(
        pair=pair,
        as_of=as_of,
        horizon_months=1,
        service_days=0,
    )
    assert isinstance(result.items, tuple)
