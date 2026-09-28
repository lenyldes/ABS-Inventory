"""HTTP-интеграционные тесты эндпоинта POST /api/forecast (задача 2.4)."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import (
    register_consume,
    register_receipt,
)
from app.main import app
from app.models.catalog import Item, Location, Supplier
from tests.forecasting_fixtures import (
    make_purchase_order,
    make_supplier_condition,
)


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def test_post_forecast_spec_scenario(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Сценарий спецификации: расход за 90 дней, 2 партии, поставка и ориентировочная цена."""
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 1)

    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        lead_time_days=5,
        package_size=Decimal("10.000"),
        min_order_qty=Decimal("20.000"),
        estimated_price=Decimal("250.00"),
    )

    # 1-я партия: 30 л
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 6, 1),
        quantity=Decimal("30.000"),
        doc_number="REC-01",
        batch_number="B-01",
        expiry_date=date(2026, 11, 1),
        unit_price=Decimal("240.00"),
    )
    # 2-я партия: 20 л
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 7, 1),
        quantity=Decimal("20.000"),
        doc_number="REC-02",
        batch_number="B-02",
        expiry_date=date(2026, 12, 1),
        unit_price=Decimal("260.00"),
    )

    # Расход 15 л оставляет две партии с ненулевыми остатками: 15 л и 20 л.
    register_consume(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 8, 15),
        quantity=Decimal("15.000"),
        doc_number="CON-01",
    )

    # Будущая поставка 15 л на 2026-09-10
    make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-101",
        expected_date=date(2026, 9, 10),
        expected_qty=Decimal("15.000"),
        unit_price=Decimal("250.00"),
    )

    db_session.commit()

    payload = {
        "sku": item.sku,
        "location": location.code,
        "as_of": as_of.isoformat(),
        "horizon_days": 30,
        "service_days": 10,
    }
    resp = client.post("/api/forecast", json=payload)
    assert resp.status_code == 200

    data = resp.json()
    assert data["sku"] == item.sku
    assert data["location"] == location.code
    assert data["as_of"] == "2026-09-01"
    assert data["horizon_start"] == "2026-09-02"
    assert data["horizon_end"] == "2026-10-01"
    assert data["days_count"] == 30

    # Метрики потребления: расход 15 за 90 дней -> 0.166667
    assert data["average_daily_consumption"] == "0.166667"
    assert data["forecast_consumption"] == "5.000"
    assert data["safety_stock"] == "1.667"
    assert data["current_stock"] == "35.000"
    assert data["available_stock"] == "35.000"
    assert data["incoming_qty"] == "15.000"

    # Точка перезаказа: 0.166667 * (5 + 10) = 2.500
    assert data["reorder_point"] == "2.500"
    assert data["unit_price"] == "250.00"
    assert data["total_cost"] is not None

    # Посуточный прогноз: ровно 30 дней
    daily = data["daily_forecast"]
    assert len(daily) == 30
    assert daily[0]["date"] == "2026-09-02"
    assert "consumption" in daily[0]
    assert "incoming" in daily[0]
    assert "expired" in daily[0]
    assert "closing_stock" in daily[0]
    assert "daily_deficit" in daily[0]

    # Структурированное объяснение: data_used, formulas, assumptions
    expl = data["explanation"]
    assert "data_used" in expl
    assert "formulas" in expl
    assert "assumptions" in expl

    data_used = {entry["name"]: entry for entry in expl["data_used"]}
    assert data_used["total_consumption_90d"]["value"] == "15.000"
    assert "Журнал движений" in data_used["gross_consumption_90d"]["source"]
    assert data_used["average_daily_consumption"]["value"] == "0.166667"
    assert data_used["current_stock"]["value"] == "35.000"
    assert data_used["available_stock"]["value"] == "35.000"
    assert data_used["batch_B-01"]["value"] == "15.000"
    assert "поступление 2026-06-01" in data_used["batch_B-01"]["source"]
    assert data_used["batch_B-02"]["value"] == "20.000"
    assert "поступление 2026-07-01" in data_used["batch_B-02"]["source"]
    assert data_used["incoming_qty"]["value"] == "15.000"
    assert "неполученных заказов" in data_used["incoming_qty"]["source"]
    assert data_used["pending_order_PO-101"]["value"] == "15.000"
    assert "ожидаемая дата 2026-09-10" in data_used["pending_order_PO-101"]["source"]
    assert data_used["unit_price"]["value"] == "250.00"
    assert "Ориентировочная цена" in data_used["unit_price"]["source"]

    # Формулы
    formulas_text = " ".join(expl["formulas"])
    assert "forecast_consumption" in formulas_text
    assert "safety_stock" in formulas_text

    # Допущения: ориентировочная цена и годность будущей поставки
    assumptions_text = " ".join(expl["assumptions"])
    assert "ориентировочная цена" in assumptions_text
    assert "годными" in assumptions_text
    assert "ROUND_HALF_UP" in assumptions_text
    assert "количества — до 3 знаков" in assumptions_text
    assert "цена и стоимость — до 2 знаков" in assumptions_text


def test_post_forecast_validation_bad_request_400(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Ошибки 400: оба горизонта, ни одного, неположительный горизонт, service_days < 0."""
    item, location, _ = base_catalog

    # 1. Оба горизонта заданы
    resp1 = client.post(
        "/api/forecast",
        json={"sku": item.sku, "location": location.code, "horizon_days": 10, "horizon_months": 1},
    )
    assert resp1.status_code == 400
    assert resp1.json()["code"] == "BAD_REQUEST"

    # 2. Ни один горизонт не задан
    resp2 = client.post(
        "/api/forecast",
        json={"sku": item.sku, "location": location.code},
    )
    assert resp2.status_code == 400
    assert resp2.json()["code"] == "BAD_REQUEST"

    # 3. horizon_days < 1
    resp3 = client.post(
        "/api/forecast",
        json={"sku": item.sku, "location": location.code, "horizon_days": 0},
    )
    assert resp3.status_code == 400

    # 4. horizon_months < 1
    resp4 = client.post(
        "/api/forecast",
        json={"sku": item.sku, "location": location.code, "horizon_months": 0},
    )
    assert resp4.status_code == 400

    # 5. service_days < 0
    resp5 = client.post(
        "/api/forecast",
        json={"sku": item.sku, "location": location.code, "horizon_days": 14, "service_days": -1},
    )
    assert resp5.status_code == 400


def test_post_forecast_not_found_404(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Ошибки 404: неизвестный SKU или неизвестная локация."""
    item, location, _ = base_catalog

    resp_sku = client.post(
        "/api/forecast",
        json={"sku": "UNKNOWN-SKU", "location": location.code, "horizon_days": 14},
    )
    assert resp_sku.status_code == 404
    assert resp_sku.json()["code"] == "NOT_FOUND"

    resp_loc = client.post(
        "/api/forecast",
        json={"sku": item.sku, "location": "UNKNOWN-LOC", "horizon_days": 14},
    )
    assert resp_loc.status_code == 404
    assert resp_loc.json()["code"] == "NOT_FOUND"


def test_post_forecast_validation_error_422(
    client: TestClient,
) -> None:
    """Ошибки 422: невалидный формат даты, отсутствие обязательных полей, лишние поля."""
    # 1. Невалидная дата
    resp1 = client.post(
        "/api/forecast",
        json={"sku": "ANY", "location": "ANY", "as_of": "invalid-date", "horizon_days": 10},
    )
    assert resp1.status_code == 422

    # 2. Не передан sku
    resp2 = client.post(
        "/api/forecast",
        json={"location": "ANY", "horizon_days": 10},
    )
    assert resp2.status_code == 422

    # 3. Лишнее поле (extra="forbid")
    resp3 = client.post(
        "/api/forecast",
        json={"sku": "ANY", "location": "ANY", "horizon_days": 10, "unknown_field": "val"},
    )
    assert resp3.status_code == 422
