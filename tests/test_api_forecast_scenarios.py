"""Дополнительные интеграционные сценарии эндпоинта POST /api/forecast (задача 2.4)."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import register_receipt
from app.main import app
from app.models.catalog import Item, Location, Supplier


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def test_post_forecast_with_horizon_months(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Проверка расчёта горизонта через horizon_months с корректным календарным сдвигом."""
    item, location, _ = base_catalog

    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 1, 10),
        quantity=Decimal("10.000"),
        doc_number="REC-MONTH",
        batch_number="B-M",
        unit_price=Decimal("100.00"),
        expiry_date=date(2027, 1, 10),
    )
    db_session.commit()

    # 31 января -> горизонт 1 месяц до 28 февраля (2026 невисокосный)
    payload = {
        "sku": item.sku,
        "location": location.code,
        "as_of": "2026-01-31",
        "horizon_months": 1,
    }
    resp = client.post("/api/forecast", json=payload)
    assert resp.status_code == 200

    data = resp.json()
    assert data["horizon_start"] == "2026-02-01"
    assert data["horizon_end"] == "2026-02-28"
    assert data["days_count"] == 28
    assert len(data["daily_forecast"]) == 28


def test_post_forecast_null_metrics_when_unavailable(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Недоступные показатели (цена, ROP при отсутствии lead_time) возвращаются как null, а не 0."""
    item, location, _ = base_catalog

    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("50.000"),
        doc_number="REC-NO-COND",
        batch_number="B-NC",
        unit_price=Decimal("100.00"),
        expiry_date=date(2027, 8, 1),
    )
    db_session.commit()

    resp = client.post(
        "/api/forecast",
        json={
            "sku": item.sku,
            "location": location.code,
            "as_of": "2026-09-01",
            "horizon_days": 30,
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    # Условия поставщика отсутствуют -> lead_time_days нет -> reorder_point is None
    assert data["reorder_point"] is None
    assert data["order_date"] is None

    # Потребление отсутствует -> 0
    assert data["average_daily_consumption"] == "0.000000"
    assert data["forecast_consumption"] == "0.000"
    assert data["recommended_qty"] == "0.000"
    assert any("Потребление за 90 дней отсутствует" in w for w in data["warnings"])


def test_post_forecast_late_correction_scenario(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Сценарий: позднее исправление поступления меняет результат повторного расчёта."""
    item, location, _ = base_catalog
    as_of = date(2026, 8, 10)

    # 1. Первоначальное поступление 10 л
    rec_res = register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-INIT",
        batch_number="B-INIT",
        unit_price=Decimal("100.00"),
        expiry_date=date(2027, 8, 1),
    )
    db_session.commit()

    resp1 = client.post(
        "/api/forecast",
        json={
            "sku": item.sku,
            "location": location.code,
            "as_of": as_of.isoformat(),
            "horizon_days": 14,
        },
    )
    assert resp1.status_code == 200
    assert resp1.json()["current_stock"] == "10.000"

    # 2. Исправление поступления: отмена старого и регистрация нового на 50 л
    rec_res.movement.status = "cancelled"
    db_session.commit()

    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("50.000"),
        doc_number="REC-AMENDED",
        batch_number="B-AMENDED",
        unit_price=Decimal("100.00"),
        expiry_date=date(2027, 8, 1),
    )
    db_session.commit()

    # 3. Повторный расчёт на ту же дату as_of
    resp2 = client.post(
        "/api/forecast",
        json={
            "sku": item.sku,
            "location": location.code,
            "as_of": as_of.isoformat(),
            "horizon_days": 14,
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["current_stock"] == "50.000"
