"""Вспомогательные фикстуры и генераторы данных для тестов прогнозирования."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder, SupplierCondition


@pytest.fixture
def base_catalog(db_session: Session) -> tuple[Item, Location, Supplier]:
    """Базовые сущности каталога для тестов прогнозирования."""
    item = Item(sku="OIL-JOJ-01", name="Масло жожоба", category="Масла", unit="л")
    location = Location(code="LOC-MS-01", name="SPA Центр")
    supplier = Supplier(supplier_id="SUP-NAT-01", name="Натуральные Масла")
    db_session.add_all([item, location, supplier])
    db_session.commit()
    return item, location, supplier


def make_supplier_condition(
    session: Session,
    item_id: int,
    supplier_id: int,
    lead_time_days: int = 5,
    package_size: Decimal = Decimal("1.000"),
    min_order_qty: Decimal = Decimal("5.000"),
    estimated_price: Decimal | None = None,
    is_primary: bool = True,
) -> SupplierCondition:
    """Создаёт и фиксирует закупочные условия для товара и поставщика."""
    cond = SupplierCondition(
        item_id=item_id,
        supplier_id=supplier_id,
        lead_time_days=lead_time_days,
        package_size=package_size,
        min_order_qty=min_order_qty,
        estimated_price=estimated_price,
        is_primary=is_primary,
    )
    session.add(cond)
    session.commit()
    return cond


def make_purchase_order(
    session: Session,
    item_id: int,
    location_id: int,
    supplier_id: int,
    doc_number: str,
    expected_date: date,
    expected_qty: Decimal,
    pending_qty: Decimal | None = None,
    received_qty: Decimal = Decimal("0.000"),
    unit_price: Decimal | None = None,
    status: str = "pending",
) -> PurchaseOrder:
    """Создаёт и сохраняет заказ поставщику с заданными параметрами."""
    po = PurchaseOrder(
        item_id=item_id,
        location_id=location_id,
        supplier_id=supplier_id,
        doc_number=doc_number,
        expected_date=expected_date,
        expected_qty=expected_qty,
        received_qty=received_qty,
        pending_qty=expected_qty if pending_qty is None else pending_qty,
        unit_price=unit_price,
        status=status,
    )
    session.add(po)
    session.commit()
    return po


def make_receipt_record(
    session: Session,
    item_id: int,
    location_id: int,
    operation_date: date,
    unit_price: Decimal,
    quantity: Decimal = Decimal("10.000"),
    doc_number: str = "DOC-REC",
    batch_number: str = "B-REC",
    supplier_id: int | None = None,
    purchase_order_id: int | None = None,
    status: str = "active",
) -> tuple[Batch, Movement]:
    """Создаёт связанную учётную партию и движение поступления."""
    batch = Batch(
        item_id=item_id,
        location_id=location_id,
        batch_number=batch_number,
        receipt_date=operation_date,
        unit_price=unit_price,
        receipt_doc_number=doc_number,
    )
    session.add(batch)
    session.flush()

    movement = Movement(
        operation_date=operation_date,
        item_id=item_id,
        location_id=location_id,
        type="receipt",
        quantity=quantity,
        doc_number=doc_number,
        batch_id=batch.id,
        supplier_id=supplier_id,
        purchase_order_id=purchase_order_id,
        status=status,
    )
    session.add(movement)
    session.commit()
    return batch, movement
