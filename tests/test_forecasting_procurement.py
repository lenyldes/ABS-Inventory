"""Интеграционные тесты репозитория закупочных условий и заказов прогнозирования (задача 2.3)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.forecasting.procurement_repository import (
    load_forecast_inputs,
    load_procurement_context,
)
from app.inventory.exceptions import EntityNotFoundError
from app.models.catalog import Item, Location, Supplier
from tests.forecasting_fixtures import (
    make_purchase_order,
    make_receipt_record,
    make_supplier_condition,
)


def test_delayed_order_not_in_pending_orders(
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Задержанная поставка (expected_date <= as_of) не попадает в pending_orders,
    а попадает в delayed_orders.
    """
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 25)

    # 1. Заказ до as_of (задержан)
    make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-DEL-01",
        expected_date=date(2026, 9, 20),
        expected_qty=Decimal("15.000"),
        unit_price=Decimal("450.00"),
    )
    # 2. Заказ ровно на as_of (задержан)
    make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-DEL-02",
        expected_date=date(2026, 9, 25),
        expected_qty=Decimal("5.000"),
        unit_price=Decimal("450.00"),
    )
    # 3. Будущий заказ (строго после as_of)
    make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-FUT-01",
        expected_date=date(2026, 9, 30),
        expected_qty=Decimal("20.000"),
        unit_price=Decimal("460.00"),
    )
    # 4. Отменённый заказ (исключается)
    make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-CANC-01",
        expected_date=date(2026, 10, 5),
        expected_qty=Decimal("10.000"),
        status="cancelled",
    )

    context = load_procurement_context(db_session, item.id, location.id, as_of)

    delayed_docs = [o.doc_number for o in context.delayed_orders]
    assert "PO-DEL-01" in delayed_docs
    assert "PO-DEL-02" in delayed_docs
    assert "PO-FUT-01" not in delayed_docs
    assert "PO-CANC-01" not in delayed_docs

    assert len(context.pending_orders) == 1
    assert context.pending_orders[0].doc_number == "PO-FUT-01"
    assert context.pending_orders[0].pending_qty == Decimal("20.000")


def test_partially_received_order_accounts_exact_pending_qty(
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Частичная приёмка (pending_qty = 8 из 20) учитывает ровно остаток 8."""
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 25)

    make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-PARTIAL-01",
        expected_date=date(2026, 10, 10),
        expected_qty=Decimal("20.000"),
        received_qty=Decimal("12.000"),
        pending_qty=Decimal("8.000"),
        unit_price=Decimal("500.00"),
        status="partially_received",
    )
    # Полностью полученный заказ (pending_qty = 0) не должен учитываться
    make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-FULL-01",
        expected_date=date(2026, 10, 12),
        expected_qty=Decimal("10.000"),
        received_qty=Decimal("10.000"),
        pending_qty=Decimal("0.000"),
        status="received",
    )

    context = load_procurement_context(db_session, item.id, location.id, as_of)

    assert len(context.pending_orders) == 1
    assert context.pending_orders[0].doc_number == "PO-PARTIAL-01"
    assert context.pending_orders[0].pending_qty == Decimal("8.000")
    assert context.pending_orders[0].unit_price == Decimal("500.00")


def test_price_source_precedence_and_as_of_cutoff(
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Поступление поставщика приоритетнее estimated_price; поступление после as_of игнорируется."""
    item, location, supplier = base_catalog

    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        estimated_price=Decimal("400.00"),
    )

    # 1. До поступлений (as_of = 2026-09-01): используется estimated_price
    ctx_before = load_procurement_context(db_session, item.id, location.id, date(2026, 9, 1))
    assert ctx_before.unit_price == Decimal("400.00")
    assert ctx_before.price_source == "estimated"

    # Активное поступление от 2026-09-10 по цене 520.00
    make_receipt_record(
        db_session,
        item.id,
        location.id,
        date(2026, 9, 10),
        unit_price=Decimal("520.00"),
        doc_number="DOC-REC-01",
        batch_number="B-REC-01",
        supplier_id=supplier.id,
    )

    # Второе поступление на будущее: 2026-09-30 по цене 600.00
    make_receipt_record(
        db_session,
        item.id,
        location.id,
        date(2026, 9, 30),
        unit_price=Decimal("600.00"),
        doc_number="DOC-REC-02",
        batch_number="B-REC-02",
        supplier_id=supplier.id,
    )

    # 2. На дату 2026-09-20: последнее поступление до as_of — от 2026-09-10 с ценой 520.00
    ctx_current = load_procurement_context(db_session, item.id, location.id, date(2026, 9, 20))
    assert ctx_current.unit_price == Decimal("520.00")
    assert ctx_current.price_source == "receipt"

    # 3. На дату 2026-10-05: последнее поступление — от 2026-09-30 с ценой 600.00
    ctx_future = load_procurement_context(db_session, item.id, location.id, date(2026, 10, 5))
    assert ctx_future.unit_price == Decimal("600.00")
    assert ctx_future.price_source == "receipt"


def test_cancelled_and_amended_movements_ignored_for_price(
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Отменённые/исправленные поступления (status == 'cancelled')
    не участвуют в определении цены.
    """
    item, location, supplier = base_catalog

    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        estimated_price=Decimal("300.00"),
    )

    # Раннее активное поступление по цене 350.00 от 2026-09-01
    make_receipt_record(
        db_session,
        item.id,
        location.id,
        date(2026, 9, 1),
        unit_price=Decimal("350.00"),
        doc_number="DOC-ACT",
        batch_number="B-ACT",
        supplier_id=supplier.id,
        status="active",
    )

    # Позднее, но отменённое поступление по ошибочной цене 999.00 от 2026-09-15
    make_receipt_record(
        db_session,
        item.id,
        location.id,
        date(2026, 9, 15),
        unit_price=Decimal("999.00"),
        doc_number="DOC-CANC",
        batch_number="B-CANC",
        supplier_id=supplier.id,
        status="cancelled",
    )

    context = load_procurement_context(db_session, item.id, location.id, date(2026, 9, 20))
    assert context.unit_price == Decimal("350.00")
    assert context.price_source == "receipt"


def test_price_from_order_supplier(
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """У поступления с purchase_order_id поставщик определяется из связанного заказа."""
    item, location, supplier = base_catalog

    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        estimated_price=None,
    )

    po = make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-FOR-REC",
        expected_date=date(2026, 9, 15),
        expected_qty=Decimal("10.000"),
        received_qty=Decimal("10.000"),
        pending_qty=Decimal("0.000"),
        unit_price=Decimal("480.00"),
        status="received",
    )

    # Поступление привязано к po.id, movement.supplier_id не заполнен
    make_receipt_record(
        db_session,
        item.id,
        location.id,
        date(2026, 9, 15),
        unit_price=Decimal("480.00"),
        doc_number="DOC-FROM-PO",
        batch_number="B-FROM-PO",
        supplier_id=None,
        purchase_order_id=po.id,
    )

    context = load_procurement_context(db_session, item.id, location.id, date(2026, 9, 20))
    assert context.unit_price == Decimal("480.00")
    assert context.price_source == "receipt"
    assert context.supplier_id == "SUP-NAT-01"


def test_load_forecast_inputs_success_and_errors(
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """load_forecast_inputs возвращает все структуры либо EntityNotFoundError
    при неверных параметрах.
    """
    item, location, supplier = base_catalog

    inputs = load_forecast_inputs(db_session, item.sku, location.code, date(2026, 9, 25))
    assert inputs.item.id == item.id
    assert inputs.location.id == location.id
    assert isinstance(inputs.batches, list)
    assert isinstance(inputs.movements, list)
    assert inputs.procurement_context is not None

    with pytest.raises(EntityNotFoundError) as exc_sku:
        load_forecast_inputs(db_session, "NON-EXISTENT-SKU", location.code, date(2026, 9, 25))
    assert exc_sku.value.details["entity"] == "Item"
    assert exc_sku.value.details["identifier"] == "NON-EXISTENT-SKU"

    with pytest.raises(EntityNotFoundError) as exc_loc:
        load_forecast_inputs(db_session, item.sku, "NON-EXISTENT-LOC", date(2026, 9, 25))
    assert exc_loc.value.details["entity"] == "Location"
    assert exc_loc.value.details["identifier"] == "NON-EXISTENT-LOC"
