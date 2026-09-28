"""HTTP-тесты эндпоинта истории версий: GET /api/movements/{id}/history."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import register_receipt
from app.main import app
from app.models.amendments import MovementVersion
from app.models.catalog import Item, Location
from app.models.inventory import Movement


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


@pytest.fixture
def catalog_setup(db_session: Session) -> tuple[Item, Location]:
    """Базовые товар и объект для тестирования версий движений."""
    item = Item(sku="OIL-API-HIST-01", name="Масло шалфея", category="Масла", unit="л")
    loc = Location(code="LOC-API-HIST-01", name="SPA Юг")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_get_movement_history_active_http(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """HTTP-тест GET /api/movements/{id}/history для активного движения."""
    item, loc = catalog_setup

    resp = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "20.000",
            "doc_number": "DOC-API-REC",
            "batch_number": "BATCH-API",
            "expiry_date": (date.today() + timedelta(days=90)).isoformat(),
            "unit_price": "250.00",
        },
    )
    assert resp.status_code == 201
    mov_id = resp.json()["id"]

    h_resp = client.get(f"/api/movements/{mov_id}/history")
    assert h_resp.status_code == 200
    data = h_resp.json()

    assert data["movement_id"] == mov_id
    assert data["is_cancelled"] is False
    assert data["current_state"]["quantity"] == "20.000"
    assert data["current_state"]["doc_number"] == "DOC-API-REC"

    assert len(data["versions"]) == 1
    v1 = data["versions"][0]
    assert v1["version_num"] == 1
    assert v1["action"] == "create"
    assert v1["reason"] == "Первичный ввод"
    assert v1["changes"] == {}
    assert v1["snapshot"]["quantity"] == "20.000"


def test_get_movement_history_cancelled_http(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """HTTP-тест GET /api/movements/{id}/history для отменённого движения."""
    item, loc = catalog_setup

    res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date.today(),
        quantity=Decimal("10.000"),
        doc_number="DOC-REC-TO-CANCEL",
        batch_number="BATCH-CANCEL",
        expiry_date=date.today() + timedelta(days=90),
        unit_price=Decimal("100.00"),
    )
    db_session.commit()

    mv = db_session.get(Movement, res.movement.id)
    assert mv is not None
    # Эмулируем отмену движения с записью версии 2
    mv.status = "cancelled"
    mv.current_version = 2
    v2_snap = dict(mv.versions[0].snapshot)
    v2_snap["status"] = "cancelled"
    v2 = MovementVersion(
        movement_id=mv.id,
        version_num=2,
        action="cancel",
        reason="Ошибочный ввод документа",
        snapshot=v2_snap,
    )
    db_session.add(v2)
    db_session.commit()

    h_resp = client.get(f"/api/movements/{mv.id}/history")
    assert h_resp.status_code == 200
    data = h_resp.json()

    assert data["movement_id"] == mv.id
    assert data["is_cancelled"] is True
    assert data["current_state"]["status"] == "cancelled"
    assert len(data["versions"]) == 2

    v1 = data["versions"][0]
    assert v1["action"] == "create"
    assert v1["changes"] == {}

    v2_item = data["versions"][1]
    assert v2_item["action"] == "cancel"
    assert v2_item["reason"] == "Ошибочный ввод документа"
    assert v2_item["changes"] == {"status": {"old": "active", "new": "cancelled"}}


def test_get_movement_history_not_found_http(client: TestClient) -> None:
    """HTTP-тест GET /api/movements/{id}/history возвращает 404 при отсутствии ID."""
    resp = client.get("/api/movements/999999/history")
    assert resp.status_code == 404
    data = resp.json()
    assert data["code"] == "NOT_FOUND"
