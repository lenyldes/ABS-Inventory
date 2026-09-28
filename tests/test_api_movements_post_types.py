"""HTTP-тесты успешной регистрации пяти типов складских движений."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.catalog import Item, Location
from app.models.inventory import Batch


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


@pytest.fixture
def base_catalog(db_session: Session) -> tuple[Item, Location]:
    """Базовые товар и объект для тестов."""
    item = Item(sku="OIL-LAV-01", name="Масло лаванды", category="Масла", unit="л")
    loc = Location(code="LOC-CENTRAL", name="Центральный склад")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_post_movement_all_five_types(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location],
) -> None:
    """Проверка успешной регистрации всех пяти типов движений."""
    item, loc = base_catalog

    # 1. receipt
    rec_resp = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "10.000",
            "doc_number": "DOC-REC-001",
            "batch_number": "BATCH-001",
            "expiry_date": (date.today() + timedelta(days=60)).isoformat(),
            "unit_price": "150.00",
        },
    )
    assert rec_resp.status_code == 201
    rec_data = rec_resp.json()
    assert rec_data["current_stock"] == "10.000"
    assert rec_data["available_stock"] == "10.000"
    assert rec_data["type"] == "receipt"
    assert rec_data["allocations"] == []

    batch = db_session.query(Batch).filter_by(batch_number="BATCH-001").one()

    # 2. consume
    cons_resp = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "consume",
            "quantity": "4.000",
            "doc_number": "DOC-CONS-001",
        },
    )
    assert cons_resp.status_code == 201
    cons_data = cons_resp.json()
    assert cons_data["current_stock"] == "6.000"
    assert cons_data["available_stock"] == "6.000"
    assert len(cons_data["allocations"]) == 1
    assert cons_data["allocations"][0]["quantity"] == "4.000"
    assert cons_data["allocations"][0]["batch_id"] == batch.id

    consume_id = cons_data["id"]
    alloc_id = cons_data["allocations"][0]["id"]

    # 3. writeoff
    wo_resp = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "writeoff",
            "quantity": "1.000",
            "doc_number": "DOC-WO-001",
            "batch_id": batch.id,
            "reason": "Порча при транспортировке",
        },
    )
    assert wo_resp.status_code == 201
    wo_data = wo_resp.json()
    assert wo_data["current_stock"] == "5.000"
    assert wo_data["available_stock"] == "5.000"

    # 4. return
    ret_resp = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "return",
            "quantity": "1.000",
            "doc_number": "DOC-RET-001",
            "parent_movement_id": consume_id,
            "parent_allocation_id": alloc_id,
            "reason": "Не использовано в процедуре",
        },
    )
    assert ret_resp.status_code == 201
    ret_data = ret_resp.json()
    assert ret_data["current_stock"] == "6.000"
    assert ret_data["available_stock"] == "6.000"

    # 5. correction
    corr_resp = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "correction",
            "quantity": "-1.000",
            "doc_number": "DOC-CORR-001",
            "batch_id": batch.id,
            "reason": "Инвентаризационная недостача",
        },
    )
    assert corr_resp.status_code == 201
    corr_data = corr_resp.json()
    assert corr_data["current_stock"] == "5.000"
    assert corr_data["available_stock"] == "5.000"
