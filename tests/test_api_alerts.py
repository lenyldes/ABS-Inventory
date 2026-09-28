"""HTTP-интеграционные тесты эндпоинта GET /api/alerts: валидация, структура и фильтры."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import register_receipt
from app.main import app
from app.models.catalog import Item, Location, Supplier
from tests.forecasting_fixtures import make_supplier_condition


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def test_get_alerts_validation_errors(client: TestClient) -> None:
    """Проверка возврата 400 и 422 при некорректных параметрах запроса."""
    bad_params = [
        ("horizon_days=0", 400),
        ("horizon_days=-5", 400),
        ("shelf_life_days_threshold=0", 400),
        ("shelf_life_days_threshold=-1", 400),
        ("no_movement_days_threshold=0", 400),
        ("limit=0", 400),
        ("limit=101", 400),
        ("offset=-1", 400),
        ("as_of=not-a-date", 422),
        ("level=supercritical", 422),
        ("type=unknown_type", 422),
    ]
    for param, expected_status in bad_params:
        resp = client.get(f"/api/alerts?{param}")
        assert resp.status_code == expected_status, f"Ошибка для {param}: {resp.status_code}"


def test_get_alerts_success_structure(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Проверка успешного ответа 200 OK, структуры данных, уровней и полей metrics."""
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 28)

    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        lead_time_days=5,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("1.000"),
    )

    # 1. Просроченная партия (срок 2026-09-15 < as_of) -> expired (critical)
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-EXP-01",
        batch_number="B-EXP-01",
        expiry_date=date(2026, 9, 15),
        unit_price=Decimal("100.00"),
    )

    # 2. Партия с приближающимся сроком годности -> expiring_soon (warning)
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="REC-SOON-01",
        batch_number="B-SOON-01",
        expiry_date=as_of + timedelta(days=10),
        unit_price=Decimal("120.00"),
    )
    db_session.commit()

    resp = client.get(
        "/api/alerts",
        params={
            "as_of": as_of.isoformat(),
            "sku": item.sku,
            "location": location.code,
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "items" in data
    assert "total" in data
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["total"] >= 2

    types = [item_data["type"] for item_data in data["items"]]
    levels = [item_data["level"] for item_data in data["items"]]
    assert "expired" in types
    assert "expiring_soon" in types
    assert "critical" in levels
    assert "warning" in levels

    # Проверка обязательных полей элемента
    for alert in data["items"]:
        assert alert["id"].startswith("alert-")
        assert alert["sku"] == item.sku
        assert alert["location"] == location.code
        assert isinstance(alert["message"], str) and len(alert["message"]) > 0
        assert isinstance(alert["metrics"], dict)
        assert alert["as_of"] == as_of.isoformat()


def test_get_alerts_filtering(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка фильтрации предупреждений по sku, location, level и type."""
    loc1 = Location(code="LOC-FLT-1", name="Филиал 1")
    loc2 = Location(code="LOC-FLT-2", name="Филиал 2")
    item1 = Item(sku="SKU-FLT-1", name="Товар 1", category="Кат 1", unit="шт")
    item2 = Item(sku="SKU-FLT-2", name="Товар 2", category="Кат 2", unit="шт")
    db_session.add_all([loc1, loc2, item1, item2])
    db_session.commit()

    as_of = date(2026, 9, 28)

    # loc1 + item1: просроченная партия (expired, critical)
    register_receipt(
        db_session,
        item=item1,
        location=loc1,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="REC-1",
        batch_number="B-1",
        expiry_date=as_of - timedelta(days=5),
        unit_price=Decimal("50.00"),
    )
    # loc2 + item2: партия с приближением срока (expiring_soon, warning)
    register_receipt(
        db_session,
        item=item2,
        location=loc2,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="REC-2",
        batch_number="B-2",
        expiry_date=as_of + timedelta(days=15),
        unit_price=Decimal("50.00"),
    )
    # Дополнительные предупреждения делают оба фильтра совместного запроса значимыми.
    register_receipt(
        db_session,
        item=item1,
        location=loc1,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="REC-3",
        batch_number="B-3",
        expiry_date=as_of + timedelta(days=15),
        unit_price=Decimal("50.00"),
    )
    register_receipt(
        db_session,
        item=item2,
        location=loc2,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="REC-4",
        batch_number="B-4",
        expiry_date=as_of - timedelta(days=5),
        unit_price=Decimal("50.00"),
    )
    db_session.commit()

    # Фильтр по location
    r_loc = client.get(
        "/api/alerts",
        params={"as_of": as_of.isoformat(), "location": "LOC-FLT-1"},
    )
    assert r_loc.status_code == 200
    for it in r_loc.json()["items"]:
        assert it["location"] == "LOC-FLT-1"

    # Фильтр по sku
    r_sku = client.get(
        "/api/alerts",
        params={"as_of": as_of.isoformat(), "sku": "SKU-FLT-2"},
    )
    assert r_sku.status_code == 200
    for it in r_sku.json()["items"]:
        assert it["sku"] == "SKU-FLT-2"

    # Фильтр по level
    r_crit = client.get(
        "/api/alerts",
        params={"as_of": as_of.isoformat(), "level": "critical"},
    )
    assert r_crit.status_code == 200
    for it in r_crit.json()["items"]:
        assert it["level"] == "critical"

    # Совместный фильтр отсекает warning в loc1 и critical в loc2.
    r_loc_crit = client.get(
        "/api/alerts",
        params={"as_of": as_of.isoformat(), "location": "LOC-FLT-1", "level": "critical"},
    )
    assert r_loc_crit.status_code == 200
    loc_crit_items = r_loc_crit.json()["items"]
    assert len(loc_crit_items) == r_loc_crit.json()["total"] == 1
    assert loc_crit_items[0]["location"] == "LOC-FLT-1"
    assert loc_crit_items[0]["level"] == "critical"
    assert loc_crit_items[0]["type"] == "expired"

    # Фильтр по type
    r_type = client.get(
        "/api/alerts",
        params={"as_of": as_of.isoformat(), "type": "expired"},
    )
    assert r_type.status_code == 200
    for it in r_type.json()["items"]:
        assert it["type"] == "expired"
