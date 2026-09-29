"""HTTP-интеграционные тесты эндпоинта POST /api/procurement/plan (подзадача 1.1)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.timezone import today_in_moscow
from app.main import app
from app.models.catalog import Item, Location, Supplier


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


@pytest.mark.parametrize(
    ("months", "expected_end", "expected_days"),
    [
        (1, "2026-10-15", 30),
        (3, "2026-12-15", 91),
        (6, "2027-03-15", 181),
        (12, "2027-09-15", 365),
    ],
)
def test_post_plan_horizon_boundaries(
    client: TestClient,
    db_session: Session,
    months: int,
    expected_end: str,
    expected_days: int,
) -> None:
    """Проверка расчёта границ горизонта для 1, 3, 6 и 12 месяцев."""
    as_of = date(2026, 9, 15)
    resp = client.post(
        "/api/procurement/plan",
        json={"as_of": as_of.isoformat(), "horizon_months": months},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["as_of"] == "2026-09-15"
    assert data["horizon_start"] == "2026-09-16"
    assert data["horizon_end"] == expected_end
    assert data["days_count"] == expected_days
    assert data["is_first_month_partial"] is True
    assert data["is_last_month_partial"] is True


def test_post_plan_month_end_and_start_partial_flags(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка признаков частичных месяцев: сдвиг на конец месяца и 1-е число."""
    resp_end = client.post(
        "/api/procurement/plan",
        json={"as_of": "2026-01-31", "horizon_months": 1},
    )
    assert resp_end.status_code == 200
    data_end = resp_end.json()
    assert data_end["horizon_start"] == "2026-02-01"
    assert data_end["horizon_end"] == "2026-02-28"
    assert data_end["days_count"] == 28
    assert data_end["is_first_month_partial"] is True
    assert data_end["is_last_month_partial"] is False

    resp_start = client.post(
        "/api/procurement/plan",
        json={"as_of": "2026-09-01", "horizon_months": 1},
    )
    assert resp_start.status_code == 200
    data_start = resp_start.json()
    assert data_start["is_first_month_partial"] is False
    assert data_start["is_last_month_partial"] is True


def test_post_plan_defaults(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка значений по умолчанию: as_of=сегодня, service_days=0, пустые фильтры."""
    resp = client.post(
        "/api/procurement/plan",
        json={"horizon_months": 3},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["as_of"] == today_in_moscow().isoformat()
    assert data["horizon_months"] == 3
    assert data["service_days"] == 0
    assert data["location"] is None
    assert data["category"] is None
    assert data["budget_limit"] is None
    assert data["items"] == []
    assert data["existing_orders"] == []
    assert data["warnings"] == []

    budget = data["budget"]
    assert budget["known_total"] == "0.00"
    assert budget["is_price_complete"] is True
    assert budget["is_dates_complete"] is True
    assert budget["unknown_price_count"] == 0
    assert budget["undated_count"] == 0
    assert len(budget["by_month"]) > 0
    assert all(m["known_total"] == "0.00" for m in budget["by_month"])
    assert budget["by_sku"] == []
    assert budget["by_category"] == []
    assert budget["by_location"] == []
    assert budget["budget_limit"] is None
    assert budget["limit_status"] is None
    assert budget["limit_difference"] is None

    explanation = data["explanation"]
    assert len(explanation["data_used"]) > 0
    assert len(explanation["formulas"]) > 0
    assert len(explanation["assumptions"]) > 0


def test_post_plan_budget_limit_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка расчёта статуса и разницы при заданном budget_limit."""
    resp = client.post(
        "/api/procurement/plan",
        json={
            "as_of": "2026-09-15",
            "horizon_months": 1,
            "budget_limit": "50000.00",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["budget_limit"] == "50000.00"

    budget = data["budget"]
    assert budget["budget_limit"] == "50000.00"
    assert budget["limit_status"] == "within"
    assert budget["limit_difference"] == "-50000.00"


def test_post_plan_bad_request_400(
    client: TestClient,
    db_session: Session,
) -> None:
    """Ошибки 400: недопустимый горизонт, отрицательные service_days и budget_limit."""
    for invalid_horizon in [0, 2, 4, 5, 7, 13, -1]:
        resp = client.post(
            "/api/procurement/plan",
            json={"horizon_months": invalid_horizon},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "BAD_REQUEST"

    resp_service = client.post(
        "/api/procurement/plan",
        json={"horizon_months": 3, "service_days": -1},
    )
    assert resp_service.status_code == 400
    assert resp_service.json()["code"] == "BAD_REQUEST"

    resp_budget = client.post(
        "/api/procurement/plan",
        json={"horizon_months": 3, "budget_limit": "-10.00"},
    )
    assert resp_budget.status_code == 400
    assert resp_budget.json()["code"] == "BAD_REQUEST"


def test_post_plan_not_found_404(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Ошибки 404: неизвестный объект или неизвестная категория."""
    item, location, _ = base_catalog

    resp_loc = client.post(
        "/api/procurement/plan",
        json={"horizon_months": 3, "location": "UNKNOWN_LOC"},
    )
    assert resp_loc.status_code == 404
    assert resp_loc.json()["code"] == "NOT_FOUND"

    resp_cat = client.post(
        "/api/procurement/plan",
        json={"horizon_months": 3, "category": "НЕИЗВЕСТНАЯ_КАТЕГОРИЯ"},
    )
    assert resp_cat.status_code == 404
    assert resp_cat.json()["code"] == "NOT_FOUND"

    resp_ok = client.post(
        "/api/procurement/plan",
        json={
            "horizon_months": 3,
            "location": location.code,
            "category": item.category,
        },
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["location"] == location.code
    assert resp_ok.json()["category"] == item.category


def test_post_plan_validation_error_422(
    client: TestClient,
) -> None:
    """Ошибки 422: отсутствие обязательных полей, неверные типы и лишние поля."""
    bad_payloads = [
        {},
        {"horizon_months": "three"},
        {"horizon_months": "3"},
        {"horizon_months": True},
        {"horizon_months": 3, "as_of": "not-a-date"},
        {"horizon_months": 3, "as_of": 1727500000},
        {"horizon_months": 3, "as_of": 1704067200},
        {"horizon_months": 3, "as_of": True},
        {"horizon_months": 3, "service_days": "five"},
        {"horizon_months": 3, "service_days": "0"},
        {"horizon_months": 3, "service_days": True},
        {"horizon_months": 3, "budget_limit": "not-a-number"},
        {"horizon_months": 3, "budget_limit": "100.123"},
        {"horizon_months": 3, "unknown_field": "val"},
    ]
    for payload in bad_payloads:
        resp = client.post("/api/procurement/plan", json=payload)
        assert resp.status_code == 422
        assert resp.json()["code"] == "VALIDATION_ERROR"
