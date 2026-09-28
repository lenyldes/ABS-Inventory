"""Тесты пересчёта заказов поставщикам при изменении и отмене приёмок."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import register_receipt
from app.main import app
from app.models.catalog import Item, Location, Supplier
from app.models.procurement import PurchaseOrder


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


def _setup_po_environment(
    session: Session,
    expected_qty: Decimal = Decimal("20.000"),
) -> tuple[Item, Location, PurchaseOrder]:
    """Создаёт тестовый товар, объект, поставщика и заказ."""
    item = Item(sku="OIL-PO-01", name="Масло сандала", category="Масла", unit="л")
    loc = Location(code="LOC-PO-01", name="SPA Север")
    supp = Supplier(supplier_id="SUP-PO-01", name="Поставщик масел")
    session.add_all([item, loc, supp])
    session.flush()

    po = PurchaseOrder(
        item_id=item.id,
        location_id=loc.id,
        supplier_id=supp.id,
        doc_number="PO-TEST-01",
        expected_date=date(2026, 10, 1),
        expected_qty=expected_qty,
        received_qty=Decimal("0.000"),
        pending_qty=expected_qty,
        status="pending",
    )
    session.add(po)
    session.commit()
    return item, loc, po


def test_order_recalculation_on_receipt_update(
    client: TestClient,
    db_session: Session,
) -> None:
    """Изменение количества поступления пересчитывает заказ в той же транзакции."""
    item, loc, po = _setup_po_environment(db_session, Decimal("20.000"))

    # Первичный приход 10.000 по заказу
    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("10.000"),
        doc_number="REC-PO-01",
        batch_number="B-PO-01",
        expiry_date=None,
        unit_price=Decimal("100.00"),
        purchase_order_id=po.id,
    )
    rec = rec_res.movement
    po.received_qty = Decimal("10.000")
    po.pending_qty = Decimal("10.000")
    po.status = "partially_received"
    db_session.commit()

    # Увеличиваем приход до 15.000 через preview + confirm
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Довоз поставщика",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "15.000"},
                }
            ],
        },
    )
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()

    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_data["preview_id"],
            "version_signature": prev_data["version_signature"],
            "reason": "Довоз поставщика",
        },
    )
    assert conf_resp.status_code == 200

    # Проверяем итоговое состояние заказа в БД
    db_po = db_session.get(PurchaseOrder, po.id)
    assert db_po is not None
    assert db_po.received_qty == Decimal("15.000")
    assert db_po.pending_qty == Decimal("5.000")
    assert db_po.status == "partially_received"


def test_order_recalculation_on_receipt_cancel(
    client: TestClient,
    db_session: Session,
) -> None:
    """Отмена приёмки восстанавливает непринятое количество заказа."""
    item, loc, po = _setup_po_environment(db_session, Decimal("20.000"))

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("10.000"),
        doc_number="REC-PO-02",
        batch_number="B-PO-02",
        expiry_date=None,
        unit_price=Decimal("100.00"),
        purchase_order_id=po.id,
    )
    rec = rec_res.movement
    po.received_qty = Decimal("10.000")
    po.pending_qty = Decimal("10.000")
    po.status = "partially_received"
    db_session.commit()

    # Отменяем приёмку
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Ошибочная приёмка чужого заказа",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "cancel",
                    "expected_version": 1,
                }
            ],
        },
    )
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()

    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_data["preview_id"],
            "version_signature": prev_data["version_signature"],
            "reason": "Ошибочная приёмка чужого заказа",
        },
    )
    assert conf_resp.status_code == 200

    db_po = db_session.get(PurchaseOrder, po.id)
    assert db_po is not None
    assert db_po.received_qty == Decimal("0.000")
    assert db_po.pending_qty == Decimal("20.000")
    assert db_po.status == "pending"
