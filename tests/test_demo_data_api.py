"""Сквозные интеграционные тесты API демонстрационного набора данных (задача 3.2)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.demo_data.loader import prepare_demo_data
from app.demo_data.scenarios import TEST_DEMO_AS_OF
from app.main import app
from tests.demo_data_api_alerts_checks import (
    verify_deficit_scenario,
    verify_expired_scenario,
    verify_expiry_scenario,
    verify_idle_scenario,
)
from tests.demo_data_api_plan_checks import (
    normalize_item_for_comparison,
    verify_incoming_scenario,
    verify_nolead_scenario,
    verify_noprice_scenario,
    verify_oil_scenario,
    verify_short_scenario,
)


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def test_demo_data_api_scenarios_e2e(client: TestClient, db_session: Session) -> None:
    """Сквозная проверка 4 API и девяти сценариев каталога на подготовленной БД."""
    mode, stats = prepare_demo_data(db_session, as_of=TEST_DEMO_AS_OF)
    assert mode == "created"
    assert stats["movements"] == 105

    # Вызовы четырёх целевых API
    stock_resp = client.get("/api/stock", params={"limit": 100})
    assert stock_resp.status_code == 200
    stock_items = stock_resp.json()["items"]

    fc_oil_resp = client.post(
        "/api/forecast",
        json={
            "sku": "DEMO-OIL",
            "location": "DEMO-MS-01",
            "as_of": TEST_DEMO_AS_OF.isoformat(),
            "horizon_months": 3,
        },
    )
    assert fc_oil_resp.status_code == 200
    fc_oil = fc_oil_resp.json()

    fc_short_resp = client.post(
        "/api/forecast",
        json={
            "sku": "DEMO-SHORT",
            "location": "DEMO-MS-02",
            "as_of": TEST_DEMO_AS_OF.isoformat(),
            "horizon_months": 3,
        },
    )
    assert fc_short_resp.status_code == 200
    fc_short = fc_short_resp.json()

    alerts_resp = client.get(
        "/api/alerts",
        params={"as_of": TEST_DEMO_AS_OF.isoformat(), "limit": 100},
    )
    assert alerts_resp.status_code == 200
    alerts_items = alerts_resp.json()["items"]

    plan_resp = client.post(
        "/api/procurement/plan",
        json={"as_of": TEST_DEMO_AS_OF.isoformat(), "horizon_months": 3},
    )
    assert plan_resp.status_code == 200
    plan = plan_resp.json()
    plan_items = plan["items"]
    existing_orders = plan["existing_orders"]

    # Сверка девяти сценариев каталога
    verify_oil_scenario(plan_items, plan["budget"], fc_oil)
    verify_deficit_scenario(alerts_items)
    verify_expiry_scenario(alerts_items)
    verify_expired_scenario(stock_items, alerts_items)
    verify_idle_scenario(alerts_items, plan_items)
    verify_short_scenario(fc_short, alerts_items)
    verify_noprice_scenario(plan_items, plan["budget"])
    verify_nolead_scenario(plan_items, plan["budget"], plan["explanation"])
    verify_incoming_scenario(plan_items, existing_orders)


def test_demo_data_api_plan_budget_breakdown_reconciliation(
    client: TestClient, db_session: Session
) -> None:
    """Сверка всех аналитических разрезов бюджета плана закупок с позициями."""
    prepare_demo_data(db_session, as_of=TEST_DEMO_AS_OF)

    resp = client.post(
        "/api/procurement/plan",
        json={"as_of": TEST_DEMO_AS_OF.isoformat(), "horizon_months": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"]
    budget = data["budget"]

    known_total = Decimal(budget["known_total"])
    total_qty = Decimal(budget["total_quantity"])

    # 1. Сверка с позициями
    item_costs = sum(
        (Decimal(it["total_cost"]) for it in items if it["total_cost"] is not None),
        Decimal("0.00"),
    )
    item_quantities = sum((Decimal(it["quantity"]) for it in items), Decimal("0.000"))
    assert item_costs == known_total
    assert item_quantities == total_qty

    # 2. Месячный разрез + undated
    month_sum = sum((Decimal(m["known_total"]) for m in budget["by_month"]), Decimal("0.00"))
    undated_cost = Decimal(budget["undated"]["known_total"])
    assert month_sum + undated_cost == known_total

    month_qty = sum((Decimal(m["total_quantity"]) for m in budget["by_month"]), Decimal("0.000"))
    undated_qty = Decimal(budget["undated"]["total_quantity"])
    assert month_qty + undated_qty == total_qty

    # 3. Разрез по SKU
    sku_sum = sum((Decimal(s["known_total"]) for s in budget["by_sku"]), Decimal("0.00"))
    sku_qty = sum((Decimal(s["total_quantity"]) for s in budget["by_sku"]), Decimal("0.000"))
    assert sku_sum == known_total
    assert sku_qty == total_qty

    # 4. Разрез по категориям
    cat_sum = sum((Decimal(c["known_total"]) for c in budget["by_category"]), Decimal("0.00"))
    cat_qty = sum((Decimal(c["total_quantity"]) for c in budget["by_category"]), Decimal("0.000"))
    assert cat_sum == known_total
    assert cat_qty == total_qty

    # 5. Разрез по объектам
    loc_sum = sum((Decimal(loc["known_total"]) for loc in budget["by_location"]), Decimal("0.00"))
    loc_qty = sum(
        (Decimal(loc["total_quantity"]) for loc in budget["by_location"]), Decimal("0.000")
    )
    assert loc_sum == known_total
    assert loc_qty == total_qty


def test_demo_data_api_repeated_preparation_determinism(
    client: TestClient, db_session: Session
) -> None:
    """Проверка детерминизма предметных ответов API после повторной подготовки (--replace)."""
    # 1. Первая подготовка
    prepare_demo_data(db_session, as_of=TEST_DEMO_AS_OF)

    stock_1 = client.get("/api/stock", params={"limit": 100}).json()["items"]
    plan_1 = client.post(
        "/api/procurement/plan",
        json={"as_of": TEST_DEMO_AS_OF.isoformat(), "horizon_months": 3},
    ).json()
    alerts_1 = client.get(
        "/api/alerts",
        params={"as_of": TEST_DEMO_AS_OF.isoformat(), "limit": 100},
    ).json()["items"]

    # 2. Повторная подготовка с --replace
    prepare_demo_data(db_session, as_of=TEST_DEMO_AS_OF, replace=True)

    stock_2 = client.get("/api/stock", params={"limit": 100}).json()["items"]
    plan_2 = client.post(
        "/api/procurement/plan",
        json={"as_of": TEST_DEMO_AS_OF.isoformat(), "horizon_months": 3},
    ).json()
    alerts_2 = client.get(
        "/api/alerts",
        params={"as_of": TEST_DEMO_AS_OF.isoformat(), "limit": 100},
    ).json()["items"]

    # Сравнение нормализованных остатков
    norm_stock_1 = sorted(
        (
            s["sku"],
            s["location"],
            Decimal(s["current_stock"]),
            Decimal(s["available_stock"]),
            Decimal(s["expired_stock"]),
        )
        for s in stock_1
    )
    norm_stock_2 = sorted(
        (
            s["sku"],
            s["location"],
            Decimal(s["current_stock"]),
            Decimal(s["available_stock"]),
            Decimal(s["expired_stock"]),
        )
        for s in stock_2
    )
    assert norm_stock_1 == norm_stock_2

    # Сравнение нормализованных позиций плана и бюджета
    norm_items_1 = sorted(normalize_item_for_comparison(it) for it in plan_1["items"])
    norm_items_2 = sorted(normalize_item_for_comparison(it) for it in plan_2["items"])
    assert norm_items_1 == norm_items_2
    assert Decimal(plan_1["budget"]["known_total"]) == Decimal(plan_2["budget"]["known_total"])
    assert Decimal(plan_1["budget"]["total_quantity"]) == Decimal(
        plan_2["budget"]["total_quantity"]
    )

    # Сравнение типов предупреждений
    norm_alerts_1 = sorted((a["sku"], a["location"], a["type"], a["level"]) for a in alerts_1)
    norm_alerts_2 = sorted((a["sku"], a["location"], a["type"], a["level"]) for a in alerts_2)
    assert norm_alerts_1 == norm_alerts_2
