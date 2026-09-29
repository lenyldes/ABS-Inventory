"""Сквозной интеграционный e2e-тест API плана повторных закупок и бюджета (подзадача 4.1)."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from tests.procurement_plan_e2e_fixtures import e2e_catalog_and_orders

__all__ = ["e2e_catalog_and_orders"]


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def test_e2e_procurement_plan_breakdowns_and_existing_orders(
    client: TestClient,
    db_session: Session,
    e2e_catalog_and_orders: dict[str, list],
) -> None:
    """Сквозной сценарий плана: сверка всех разрезов, покрытие заказами и неизменность forecast."""
    as_of = date(2026, 9, 15)

    resp = client.post(
        "/api/procurement/plan",
        json={
            "as_of": as_of.isoformat(),
            "horizon_months": 3,
            "service_days": 3,
            "budget_limit": "500000.00",
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    # 1. Проверка структуры ответа и границ
    assert data["as_of"] == "2026-09-15"
    assert data["horizon_start"] == "2026-09-16"
    assert data["horizon_end"] == "2026-12-15"
    assert data["days_count"] == 91
    assert data["budget_limit"] == "500000.00"

    # 2. Существующие оформленные заказы отражены отдельно
    existing_orders = data["existing_orders"]
    assert len(existing_orders) == 2
    existing_docs = {o["doc_number"] for o in existing_orders}
    assert existing_docs == {"PO-OIL-MSK-01", "PO-GEL-MSK-01"}

    # 3. Позиции плана: сформированы рекомендации
    items = data["items"]
    assert len(items) > 0

    # Существующие заказы исключены из новых затрат
    item_costs = [Decimal(it["total_cost"]) for it in items if it["total_cost"] is not None]
    items_cost_sum = sum(item_costs, Decimal("0.00"))
    items_qty_sum = sum((Decimal(it["quantity"]) for it in items), Decimal("0.000"))

    budget = data["budget"]
    known_total = Decimal(budget["known_total"])
    total_qty = Decimal(budget["total_quantity"])
    assert known_total == items_cost_sum
    assert total_qty == items_qty_sum

    # Стоимость оформленных заказов (100*100 + 60*150 = 19000 руб.) исключена из бюджета плана
    existing_total_cost = sum(
        Decimal(o["pending_qty"]) * Decimal(o["unit_price"]) for o in existing_orders
    )
    assert existing_total_cost == Decimal("19000.00")

    # 4. Виртуальное покрытие потребности:
    # Для SKU-OIL в LOC-MSK оформленный заказ 100 л отодвигает первый заказ на конец сентября
    oil_items = [it for it in items if it["sku"] == "SKU-OIL" and it["location"] == "LOC-MSK"]
    assert len(oil_items) > 0
    first_oil_item = oil_items[0]
    # При остатке 100 л + заказе 100 л = 200 л расход 10 л/д покрыт до 04.10.
    # Первый рекомендуемый заказ формируется позже as_of (2026-09-15)
    assert date.fromisoformat(first_oil_item["order_date"]) > as_of

    # 5. Сверка всех аналитических разрезов бюджета:
    # 5.1 Календарный разрез по месяцам + undated == known_total
    month_sum = sum((Decimal(m["known_total"]) for m in budget["by_month"]), Decimal("0.00"))
    undated_cost = Decimal(budget["undated"]["known_total"])
    assert month_sum + undated_cost == known_total

    month_qty = sum((Decimal(m["total_quantity"]) for m in budget["by_month"]), Decimal("0.000"))
    undated_qty = Decimal(budget["undated"]["total_quantity"])
    assert month_qty + undated_qty == total_qty

    # 5.2 Разрез по SKU == known_total и total_quantity
    sku_sum = sum((Decimal(s["known_total"]) for s in budget["by_sku"]), Decimal("0.00"))
    sku_qty = sum((Decimal(s["total_quantity"]) for s in budget["by_sku"]), Decimal("0.000"))
    assert sku_sum == known_total
    assert sku_qty == total_qty

    # 5.3 Разрез по категориям == known_total и total_quantity
    cat_sum = sum((Decimal(c["known_total"]) for c in budget["by_category"]), Decimal("0.00"))
    cat_qty = sum((Decimal(c["total_quantity"]) for c in budget["by_category"]), Decimal("0.000"))
    assert cat_sum == known_total
    assert cat_qty == total_qty

    # 5.4 Разрез по объектам == known_total и total_quantity
    loc_sum = sum((Decimal(loc["known_total"]) for loc in budget["by_location"]), Decimal("0.00"))
    loc_qty = sum(
        (Decimal(loc["total_quantity"]) for loc in budget["by_location"]), Decimal("0.000")
    )
    assert loc_sum == known_total
    assert loc_qty == total_qty

    # 6. Проверка лимита бюджета
    assert budget["budget_limit"] == "500000.00"
    assert budget["limit_status"] == "within"
    expected_diff = known_total - Decimal("500000.00")
    assert Decimal(budget["limit_difference"]) == expected_diff

    # 7. Проверка фильтров: по объекту и по категории
    resp_loc = client.post(
        "/api/procurement/plan",
        json={"as_of": as_of.isoformat(), "horizon_months": 3, "location": "LOC-MSK"},
    )
    assert resp_loc.status_code == 200
    loc_data = resp_loc.json()
    assert all(it["location"] == "LOC-MSK" for it in loc_data["items"])

    resp_cat = client.post(
        "/api/procurement/plan",
        json={"as_of": as_of.isoformat(), "horizon_months": 3, "category": "Масла"},
    )
    assert resp_cat.status_code == 200
    cat_data = resp_cat.json()
    assert all(it["category"] == "Масла" for it in cat_data["items"])

    # 8. Проверка неизменности работы и контракта /api/forecast
    resp_forecast = client.post(
        "/api/forecast",
        json={
            "sku": "SKU-OIL",
            "location": "LOC-MSK",
            "as_of": as_of.isoformat(),
            "horizon_months": 3,
            "service_days": 3,
        },
    )
    assert resp_forecast.status_code == 200
    fc_data = resp_forecast.json()

    # Контракт ответа /api/forecast сохранён полностью
    assert "daily_forecast" in fc_data
    assert "explanation" in fc_data
    assert Decimal(fc_data["average_daily_consumption"]) == Decimal("10.000")
    assert Decimal(fc_data["available_stock"]) == Decimal("100.000")
    assert Decimal(fc_data["incoming_qty"]) == Decimal("100.000")
    assert Decimal(fc_data["unit_price"]) == Decimal("100.00")
    assert fc_data["recommended_qty"] is not None
    assert fc_data["total_cost"] is not None
