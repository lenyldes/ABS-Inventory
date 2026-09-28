"""Тесты ORM-моделей закупок (SupplierCondition, PurchaseOrder)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import Item, Location, Supplier
from app.models.procurement import PurchaseOrder, SupplierCondition


def test_supplier_conditions_relations_and_precision(db_session: Session) -> None:
    """Проверяет связи, точность Decimal и ограничения условий поставщика."""
    item = Item(sku="SCR-01", name="Скраб кофейный", category="Скрабы", unit="кг")
    supplier = Supplier(supplier_id="SUP-02", name="ОрганикТрейд")
    db_session.add_all([item, supplier])
    db_session.commit()

    cond = SupplierCondition(
        item_id=item.id,
        supplier_id=supplier.id,
        lead_time_days=7,
        package_size=Decimal("0.500"),
        min_order_qty=Decimal("5.000"),
        estimated_price=Decimal("1250.75"),
        is_primary=True,
    )
    db_session.add(cond)
    db_session.commit()

    saved_cond = db_session.get(SupplierCondition, cond.id)
    assert saved_cond is not None
    assert saved_cond.item.sku == "SCR-01"
    assert saved_cond.supplier.name == "ОрганикТрейд"
    assert saved_cond.package_size == Decimal("0.500")
    assert saved_cond.min_order_qty == Decimal("5.000")
    assert saved_cond.estimated_price == Decimal("1250.75")
    assert saved_cond.is_primary is True


def test_supplier_conditions_unique_pair_and_primary_constraint(db_session: Session) -> None:
    """Проверяет уникальность пары (товар, поставщик) и максимум одного основного поставщика."""
    item = Item(sku="CREAM-01", name="Крем для лица", category="Кремы", unit="шт")
    sup1 = Supplier(supplier_id="SUP-03", name="БьютиЛаб")
    sup2 = Supplier(supplier_id="SUP-04", name="КосметикГрупп")
    db_session.add_all([item, sup1, sup2])
    db_session.commit()

    cond1 = SupplierCondition(
        item_id=item.id,
        supplier_id=sup1.id,
        lead_time_days=5,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("10.000"),
        is_primary=True,
    )
    db_session.add(cond1)
    db_session.commit()

    # Повторная привязка того же поставщика к тому же товару запрещена
    cond_dup_pair = SupplierCondition(
        item_id=item.id,
        supplier_id=sup1.id,
        lead_time_days=3,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("5.000"),
        is_primary=False,
    )
    db_session.add(cond_dup_pair)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Второй основной поставщик для того же товара запрещён частичным уникальным индексом
    cond_second_primary = SupplierCondition(
        item_id=item.id,
        supplier_id=sup2.id,
        lead_time_days=4,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("5.000"),
        is_primary=True,
    )
    db_session.add(cond_second_primary)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_supplier_conditions_check_constraints(db_session: Session) -> None:
    """Проверяет проверки допустимых значений для закупочных условий."""
    item = Item(sku="SERUM-01", name="Сыворотка", category="Уход", unit="шт")
    sup = Supplier(supplier_id="SUP-05", name="ПремиумЛаб")
    db_session.add_all([item, sup])
    db_session.commit()

    # lead_time_days < 1
    cond_bad_lead = SupplierCondition(
        item_id=item.id,
        supplier_id=sup.id,
        lead_time_days=0,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("1.000"),
    )
    db_session.add(cond_bad_lead)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # package_size <= 0
    cond_bad_package = SupplierCondition(
        item_id=item.id,
        supplier_id=sup.id,
        lead_time_days=3,
        package_size=Decimal("0.000"),
        min_order_qty=Decimal("1.000"),
    )
    db_session.add(cond_bad_package)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_purchase_order_creation_relations_and_precision(db_session: Session) -> None:
    """Проверяет создание заказа, связи, точность Decimal и проверку уникальности на объекте."""
    item = Item(sku="OIL-002", name="Масло миндальное", category="Масла", unit="л")
    loc1 = Location(code="SPB-01", name="SPA Невский")
    loc2 = Location(code="SPB-02", name="SPA Лахта")
    sup = Supplier(supplier_id="SUP-06", name="АромаСевер")
    db_session.add_all([item, loc1, loc2, sup])
    db_session.commit()

    po = PurchaseOrder(
        item_id=item.id,
        location_id=loc1.id,
        supplier_id=sup.id,
        doc_number="PO-2026-001",
        expected_date=date(2026, 10, 15),
        expected_qty=Decimal("25.500"),
        received_qty=Decimal("10.000"),
        pending_qty=Decimal("15.500"),
        unit_price=Decimal("890.50"),
        status="partially_received",
    )
    db_session.add(po)
    db_session.commit()

    saved_po = db_session.get(PurchaseOrder, po.id)
    assert saved_po is not None
    assert saved_po.item.sku == "OIL-002"
    assert saved_po.location.code == "SPB-01"
    assert saved_po.supplier.supplier_id == "SUP-06"
    assert saved_po.expected_qty == Decimal("25.500")
    assert saved_po.received_qty == Decimal("10.000")
    assert saved_po.pending_qty == Decimal("15.500")
    assert saved_po.unit_price == Decimal("890.50")
    assert saved_po.status == "partially_received"

    # Дубликат doc_number на том же объекте запрещён
    po_dup = PurchaseOrder(
        item_id=item.id,
        location_id=loc1.id,
        supplier_id=sup.id,
        doc_number="PO-2026-001",
        expected_date=date(2026, 10, 20),
        expected_qty=Decimal("10.000"),
        pending_qty=Decimal("10.000"),
    )
    db_session.add(po_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Тот же doc_number на ДРУГОМ объекте разрешён
    po_other_loc = PurchaseOrder(
        item_id=item.id,
        location_id=loc2.id,
        supplier_id=sup.id,
        doc_number="PO-2026-001",
        expected_date=date(2026, 10, 20),
        expected_qty=Decimal("10.000"),
        pending_qty=Decimal("10.000"),
    )
    db_session.add(po_other_loc)
    db_session.commit()
    assert po_other_loc.id is not None


def test_purchase_order_check_constraints(db_session: Session) -> None:
    """Проверяет ограничения значений и допустимых статусов заказов."""
    item = Item(sku="MASK-01", name="Маска глиняная", category="Маски", unit="кг")
    loc = Location(code="EKB-01", name="SPA Исеть")
    sup = Supplier(supplier_id="SUP-07", name="УралКосметик")
    db_session.add_all([item, loc, sup])
    db_session.commit()

    # received_qty > expected_qty
    po_bad_received = PurchaseOrder(
        item_id=item.id,
        location_id=loc.id,
        supplier_id=sup.id,
        doc_number="PO-BAD-01",
        expected_date=date(2026, 10, 10),
        expected_qty=Decimal("10.000"),
        received_qty=Decimal("12.000"),
        pending_qty=Decimal("0.000"),
    )
    db_session.add(po_bad_received)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # status вне допустимого множества
    po_bad_status = PurchaseOrder(
        item_id=item.id,
        location_id=loc.id,
        supplier_id=sup.id,
        doc_number="PO-BAD-02",
        expected_date=date(2026, 10, 10),
        expected_qty=Decimal("10.000"),
        pending_qty=Decimal("10.000"),
        status="invalid_status",
    )
    db_session.add(po_bad_status)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
