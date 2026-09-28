"""Интеграционные тесты для задачи 4.3: конкуренция подтверждения с новыми операциями."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.inventory.operations import register_consume, register_receipt
from app.main import app
from app.models.catalog import Item, Location, Supplier
from app.models.procurement import PurchaseOrder


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


def test_concurrent_confirm_versus_new_consume(
    client: TestClient,
    db_session: Session,
) -> None:
    """Конкурентный расход между preview и confirm приводит к 409 stale_preview."""
    item = Item(sku="OIL-CC-01", name="Масло кедра", category="Масла", unit="л")
    loc = Location(code="LOC-CC-01", name="SPA Центр")
    db_session.add_all([item, loc])
    db_session.commit()

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("20.000"),
        doc_number="REC-CC-01",
        batch_number="B-CC-01",
        expiry_date=date(2027, 9, 1),
        unit_price=Decimal("150.00"),
    )
    db_session.commit()
    rec = rec_res.movement

    # Делаем preview на изменение количества прихода
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Конкурентная проверка",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "18.000"},
                }
            ],
        },
    ).json()

    # Параллельно в отдельной сессии регистрируем новый расход
    factory = get_session_factory()

    def run_consume() -> None:
        session = factory()
        try:
            with session.begin():
                it = session.get(Item, item.id)
                lc = session.get(Location, loc.id)
                assert it is not None and lc is not None
                register_consume(
                    session,
                    item=it,
                    location=lc,
                    operation_date=date(2026, 9, 5),
                    quantity=Decimal("5.000"),
                    doc_number="CONS-CC-NEW",
                )
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(run_consume).result()

    # Confirm должен вернуть 409 Conflict stale_preview
    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_resp["preview_id"],
            "version_signature": prev_resp["version_signature"],
            "reason": "Конкурентная проверка",
        },
    )
    assert conf_resp.status_code == 409
    assert conf_resp.json()["code"] == "stale_preview"


def test_concurrent_confirm_versus_new_po_receipt(
    client: TestClient,
    db_session: Session,
) -> None:
    """Конкурентная приёмка по заказу между preview и confirm приводит к 409 stale_preview."""
    item = Item(sku="OIL-CC-02", name="Масло мяты", category="Масла", unit="л")
    loc = Location(code="LOC-CC-02", name="SPA Восток")
    supp = Supplier(supplier_id="SUP-CC-02", name="Поставщик мяты")
    db_session.add_all([item, loc, supp])
    db_session.flush()

    po = PurchaseOrder(
        item_id=item.id,
        location_id=loc.id,
        supplier_id=supp.id,
        doc_number="PO-CC-02",
        expected_date=date(2026, 10, 1),
        expected_qty=Decimal("30.000"),
        received_qty=Decimal("0.000"),
        pending_qty=Decimal("30.000"),
        status="pending",
    )
    db_session.add(po)
    db_session.commit()

    rec1_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-CC-2A",
        batch_number="B-CC-2A",
        expiry_date=date(2027, 9, 1),
        unit_price=Decimal("200.00"),
        purchase_order_id=po.id,
    )
    rec1 = rec1_res.movement
    po.received_qty = Decimal("10.000")
    po.pending_qty = Decimal("20.000")
    po.status = "partially_received"
    db_session.commit()

    # Preview для первого прихода
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Тест конкурентной приёмки",
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

    # Параллельно регистрируем второй приход по тому же заказу
    factory = get_session_factory()

    def run_second_receipt() -> None:
        session = factory()
        try:
            with session.begin():
                it = session.get(Item, item.id)
                lc = session.get(Location, loc.id)
                p_order = session.get(PurchaseOrder, po.id)
                assert it is not None and lc is not None and p_order is not None
                register_receipt(
                    session,
                    item=it,
                    location=lc,
                    operation_date=date(2026, 9, 2),
                    quantity=Decimal("10.000"),
                    doc_number="REC-CC-2B",
                    batch_number="B-CC-2B",
                    expiry_date=date(2027, 9, 1),
                    unit_price=Decimal("200.00"),
                    purchase_order_id=p_order.id,
                )
                p_order.received_qty += Decimal("10.000")
                p_order.pending_qty -= Decimal("10.000")
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(run_second_receipt).result()

    # Confirm первого превью отклоняется из-за изменения состояния
    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_resp["preview_id"],
            "version_signature": prev_resp["version_signature"],
            "reason": "Тест конкурентной приёмки",
        },
    )
    assert conf_resp.status_code == 409
    assert conf_resp.json()["code"] == "stale_preview"
