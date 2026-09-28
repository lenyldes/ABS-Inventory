"""Интеграционные тесты связи поступления с заказом поставщику на PostgreSQL."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.inventory.exceptions import InvalidMovementError
from app.inventory.operations import register_receipt
from app.models.catalog import Item, Location, Supplier
from app.models.procurement import PurchaseOrder


@pytest.fixture
def procurement_setup(db_session: Session) -> tuple[Item, Location, Supplier, PurchaseOrder]:
    """Подготовленный заказ поставщику для товара и объекта."""
    item = Item(sku="OIL-PO-01", name="Масло жожоба", category="Масла", unit="л")
    loc = Location(code="LOC-PO-01", name="SPA Юг")
    sup = Supplier(supplier_id="SUP-PO-01", name="Поставщик Юг")
    db_session.add_all([item, loc, sup])
    db_session.commit()

    po = PurchaseOrder(
        item_id=item.id,
        location_id=loc.id,
        supplier_id=sup.id,
        doc_number="PO-100",
        expected_date=date(2026, 9, 25),
        expected_qty=Decimal("10.000"),
        received_qty=Decimal("0.000"),
        pending_qty=Decimal("10.000"),
        unit_price=Decimal("500.00"),
        status="pending",
    )
    db_session.add(po)
    db_session.commit()
    return item, loc, sup, po


def test_partial_and_full_receipt_against_purchase_order(
    db_session: Session,
    procurement_setup: tuple[Item, Location, Supplier, PurchaseOrder],
) -> None:
    """Частичная и полная приёмка заказа поставщику обновляет pending_qty и статус."""
    item, loc, _, po = procurement_setup

    # 1. Частичная приёмка 4 литров
    res1 = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("4.000"),
        doc_number="REC-PO-PARTIAL",
        batch_number="B-PO-1",
        expiry_date=date(2027, 3, 20),
        unit_price=Decimal("500.00"),
        purchase_order_id=po.id,
    )
    db_session.commit()

    assert res1.current_stock == Decimal("4.000")
    po_db = db_session.get(PurchaseOrder, po.id)
    assert po_db is not None
    assert po_db.received_qty == Decimal("4.000")
    assert po_db.pending_qty == Decimal("6.000")
    assert po_db.status == "partially_received"

    # 2. Окончательная приёмка оставшихся 6 литров
    res2 = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 21),
        quantity=Decimal("6.000"),
        doc_number="REC-PO-FINAL",
        batch_number="B-PO-2",
        expiry_date=date(2027, 3, 20),
        unit_price=Decimal("500.00"),
        purchase_order_id=po.id,
    )
    db_session.commit()

    assert res2.current_stock == Decimal("10.000")
    po_db_final = db_session.get(PurchaseOrder, po.id)
    assert po_db_final is not None
    assert po_db_final.received_qty == Decimal("10.000")
    assert po_db_final.pending_qty == Decimal("0.000")
    assert po_db_final.status == "received"


def test_excess_pending_qty_rejection(
    db_session: Session,
    procurement_setup: tuple[Item, Location, Supplier, PurchaseOrder],
) -> None:
    """Приёмка с количеством, превышающим pending_qty заказа, отклоняется."""
    item, loc, _, po = procurement_setup

    with pytest.raises(InvalidMovementError) as exc_info:
        register_receipt(
            db_session,
            item=item,
            location=loc,
            operation_date=date(2026, 9, 20),
            quantity=Decimal("15.000"),  # pending_qty = 10.000
            doc_number="REC-PO-EXCESS",
            batch_number="B-EXCESS",
            expiry_date=None,
            unit_price=Decimal("500.00"),
            purchase_order_id=po.id,
        )
    db_session.rollback()

    assert exc_info.value.code == "EXCESS_ORDER_QTY"
    po_db = db_session.get(PurchaseOrder, po.id)
    assert po_db is not None
    assert po_db.received_qty == Decimal("0.000")
    assert po_db.status == "pending"


def test_order_mismatch_item_location_or_supplier(
    db_session: Session,
    procurement_setup: tuple[Item, Location, Supplier, PurchaseOrder],
) -> None:
    """Несовпадение товара, объекта или поставщика отклоняет приёмку."""
    _, loc, _, po = procurement_setup

    # Создаём другой товар
    other_item = Item(sku="OTHER-ITEM-01", name="Другой товар", category="Разное", unit="л")
    db_session.add(other_item)
    db_session.commit()

    with pytest.raises(InvalidMovementError) as exc_info:
        register_receipt(
            db_session,
            item=other_item,
            location=loc,
            operation_date=date(2026, 9, 20),
            quantity=Decimal("2.000"),
            doc_number="REC-MISMATCH",
            batch_number="B-M",
            expiry_date=None,
            unit_price=Decimal("500.00"),
            purchase_order_id=po.id,
        )
    db_session.rollback()
    assert exc_info.value.code == "ORDER_MISMATCH"
