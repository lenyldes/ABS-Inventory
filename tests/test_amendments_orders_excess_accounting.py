"""Тесты проверки пересчёта заказов: отказ при превышении и отсутствие двойного учёта."""

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
    item = Item(sku="OIL-PO-02", name="Масло сандала", category="Масла", unit="л")
    loc = Location(code="LOC-PO-02", name="SPA Север")
    supp = Supplier(supplier_id="SUP-PO-02", name="Поставщик масел")
    session.add_all([item, loc, supp])
    session.flush()

    po = PurchaseOrder(
        item_id=item.id,
        location_id=loc.id,
        supplier_id=supp.id,
        doc_number="PO-TEST-02",
        expected_date=date(2026, 10, 1),
        expected_qty=expected_qty,
        received_qty=Decimal("0.000"),
        pending_qty=expected_qty,
        status="pending",
    )
    session.add(po)
    session.commit()
    return item, loc, po


def test_order_recalculation_rejects_excess_receipt(
    client: TestClient,
    db_session: Session,
) -> None:
    """Превышение ожидаемого объёма заказа блокирует подтверждение с 422."""
    item, loc, po = _setup_po_environment(db_session, Decimal("10.000"))

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("10.000"),
        doc_number="REC-PO-03",
        batch_number="B-PO-03",
        expiry_date=None,
        unit_price=Decimal("100.00"),
        purchase_order_id=po.id,
    )
    rec = rec_res.movement
    po.received_qty = Decimal("10.000")
    po.pending_qty = Decimal("0.000")
    po.status = "received"
    db_session.commit()

    # Попытка увеличить приёмку до 15.000 при заказе 10.000
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Попытка избытка",
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
            "reason": "Попытка избытка",
        },
    )
    assert conf_resp.status_code == 422
    assert conf_resp.json()["code"] == "EXCESS_ORDER_RECEIPT"

    # Заказ не изменился
    db_po = db_session.get(PurchaseOrder, po.id)
    assert db_po is not None
    assert db_po.received_qty == Decimal("10.000")
    assert db_po.pending_qty == Decimal("0.000")


def test_order_recalculation_no_double_accounting(
    client: TestClient,
    db_session: Session,
) -> None:
    """Многократные и многопартийные приходы не приводят к двойному учёту."""
    item, loc, po = _setup_po_environment(db_session, Decimal("30.000"))

    # Два прихода по 10.000
    rec1_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("10.000"),
        doc_number="REC-PO-4A",
        batch_number="B-PO-4A",
        expiry_date=None,
        unit_price=Decimal("100.00"),
        purchase_order_id=po.id,
    )
    rec2_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 21),
        quantity=Decimal("10.000"),
        doc_number="REC-PO-4B",
        batch_number="B-PO-4B",
        expiry_date=None,
        unit_price=Decimal("100.00"),
        purchase_order_id=po.id,
    )
    rec1 = rec1_res.movement
    rec2 = rec2_res.movement
    po.received_qty = Decimal("20.000")
    po.pending_qty = Decimal("10.000")
    po.status = "partially_received"
    db_session.commit()

    # Исправляем первый приход до 12.000
    prev1 = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Уточнение А",
            "operations": [
                {
                    "movement_id": rec1.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "12.000"},
                }
            ],
        },
    ).json()
    client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev1["preview_id"],
            "version_signature": prev1["version_signature"],
            "reason": "Уточнение А",
        },
    )

    db_po = db_session.get(PurchaseOrder, po.id)
    assert db_po is not None
    assert db_po.received_qty == Decimal("22.000")
    assert db_po.pending_qty == Decimal("8.000")

    # Исправляем второй приход до 18.000, закрывая заказ на 30.000
    prev2 = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Уточнение Б",
            "operations": [
                {
                    "movement_id": rec2.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "18.000"},
                }
            ],
        },
    ).json()
    client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev2["preview_id"],
            "version_signature": prev2["version_signature"],
            "reason": "Уточнение Б",
        },
    )

    db_session.refresh(db_po)
    assert db_po.received_qty == Decimal("30.000")
    assert db_po.pending_qty == Decimal("0.000")
    assert db_po.status == "received"
