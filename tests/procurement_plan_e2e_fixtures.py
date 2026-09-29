"""Фикстуры для сквозных сценариев тестирования плана закупок (e2e)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.inventory.operations import register_consume, register_receipt
from app.models.catalog import Item, Location, Supplier
from tests.forecasting_fixtures import (
    make_purchase_order,
    make_supplier_condition,
)


@pytest.fixture
def e2e_catalog_and_orders(db_session: Session) -> dict[str, list]:
    """Создаёт объекты, поставщиков, товары, остатки, расход и оформленные заказы."""
    loc_msk = Location(code="LOC-MSK", name="Москва Склад")
    loc_spb = Location(code="LOC-SPB", name="СПб Склад")
    db_session.add_all([loc_msk, loc_spb])

    sup1 = Supplier(supplier_id="SUP-1", name="Поставщик Альфа")
    sup2 = Supplier(supplier_id="SUP-2", name="Поставщик Бета")
    db_session.add_all([sup1, sup2])

    it_oil = Item(sku="SKU-OIL", name="Масло косметическое", category="Масла", unit="л")
    it_crm = Item(sku="SKU-CRM", name="Крем для лица", category="Кремы", unit="шт")
    it_gel = Item(sku="SKU-GEL", name="Гель для душа", category="Гели", unit="шт")
    db_session.add_all([it_oil, it_crm, it_gel])
    db_session.commit()

    # Условия поставщиков
    make_supplier_condition(
        db_session,
        it_oil.id,
        sup1.id,
        lead_time_days=5,
        package_size=Decimal("10.000"),
        min_order_qty=Decimal("20.000"),
        estimated_price=Decimal("100.00"),
    )
    make_supplier_condition(
        db_session,
        it_crm.id,
        sup1.id,
        lead_time_days=7,
        package_size=Decimal("5.000"),
        min_order_qty=Decimal("10.000"),
        estimated_price=Decimal("200.00"),
    )
    make_supplier_condition(
        db_session,
        it_gel.id,
        sup2.id,
        lead_time_days=10,
        package_size=Decimal("12.000"),
        min_order_qty=Decimal("24.000"),
        estimated_price=Decimal("150.00"),
    )

    # 1. Товар SKU-OIL на складе LOC-MSK:
    # 900 л списано за 90 дней (расход 10.000 л/день), остаток 100 л на 15.09
    register_receipt(
        db_session,
        item=it_oil,
        location=loc_msk,
        operation_date=date(2026, 6, 17),
        quantity=Decimal("900.000"),
        doc_number="REC-OIL-BASE",
        batch_number="B-OIL-0",
        unit_price=Decimal("100.00"),
        expiry_date=date(2027, 6, 1),
    )
    register_consume(
        db_session,
        item=it_oil,
        location=loc_msk,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("900.000"),
        doc_number="CONS-OIL-90D",
    )
    register_receipt(
        db_session,
        item=it_oil,
        location=loc_msk,
        operation_date=date(2026, 9, 14),
        quantity=Decimal("100.000"),
        doc_number="REC-OIL-CURR",
        batch_number="B-OIL-1",
        unit_price=Decimal("100.00"),
        expiry_date=date(2027, 6, 1),
    )
    po_oil = make_purchase_order(
        db_session,
        it_oil.id,
        loc_msk.id,
        sup1.id,
        doc_number="PO-OIL-MSK-01",
        expected_date=date(2026, 9, 21),
        expected_qty=Decimal("100.000"),
        pending_qty=Decimal("100.000"),
        unit_price=Decimal("100.00"),
    )

    # 2. Товар SKU-CRM на складе LOC-SPB:
    # 450 шт списано за 90 дней (расход 5.000 шт/день), остаток 10 шт на 15.09, заказов нет
    register_receipt(
        db_session,
        item=it_crm,
        location=loc_spb,
        operation_date=date(2026, 6, 17),
        quantity=Decimal("460.000"),
        doc_number="REC-CRM-BASE",
        batch_number="B-CRM-1",
        unit_price=Decimal("200.00"),
        expiry_date=date(2027, 6, 1),
    )
    register_consume(
        db_session,
        item=it_crm,
        location=loc_spb,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("450.000"),
        doc_number="CONS-CRM-90D",
    )

    # 3. Товар SKU-GEL на складе LOC-MSK:
    # 180 шт списано за 90 дней (расход 2.000 шт/день), остаток 0, оформленный заказ 60 шт на 16.09
    register_receipt(
        db_session,
        item=it_gel,
        location=loc_msk,
        operation_date=date(2026, 6, 17),
        quantity=Decimal("180.000"),
        doc_number="REC-GEL-BASE",
        batch_number="B-GEL-0",
        unit_price=Decimal("150.00"),
        expiry_date=date(2027, 6, 1),
    )
    register_consume(
        db_session,
        item=it_gel,
        location=loc_msk,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("180.000"),
        doc_number="CONS-GEL-90D",
    )
    po_gel = make_purchase_order(
        db_session,
        it_gel.id,
        loc_msk.id,
        sup2.id,
        doc_number="PO-GEL-MSK-01",
        expected_date=date(2026, 9, 16),
        expected_qty=Decimal("60.000"),
        pending_qty=Decimal("60.000"),
        unit_price=Decimal("150.00"),
    )

    return {
        "locations": [loc_msk, loc_spb],
        "suppliers": [sup1, sup2],
        "items": [it_oil, it_crm, it_gel],
        "orders": [po_oil, po_gel],
    }
