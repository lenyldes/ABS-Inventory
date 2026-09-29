"""Вспомогательные проверки сценариев прогноза и плана закупок в тестах demo-data."""

from decimal import Decimal
from typing import Any

from app.demo_data.scenarios import get_demo_scenario


def verify_oil_scenario(
    plan_items: list[dict[str, Any]],
    plan_budget: dict[str, Any],
    fc_oil: dict[str, Any],
) -> None:
    """Сверка сценария 1: oil-quarter-plan."""
    sc1 = get_demo_scenario("oil-quarter-plan")
    assert Decimal(fc_oil["current_stock"]) == sc1.forecast_expected["current_stock"]
    assert (
        Decimal(fc_oil["average_daily_consumption"])
        == sc1.forecast_expected["average_daily_consumption"]
    )
    assert Decimal(fc_oil["recommended_qty"]) == sc1.forecast_expected["recommended_qty"]
    assert Decimal(fc_oil["unit_price"]) == sc1.forecast_expected["unit_price"]
    assert Decimal(fc_oil["total_cost"]) == sc1.forecast_expected["total_cost"]
    assert fc_oil["order_date"] == sc1.forecast_expected["order_date"].isoformat()

    oil_plan = [
        it
        for it in plan_items
        if it["sku"] == sc1.expected["sku"] and it["location"] == sc1.expected["location"]
    ]
    assert len(oil_plan) == 2
    first_oil = oil_plan[0]
    assert first_oil["order_date"] == sc1.expected["order_date"].isoformat()
    assert first_oil["delivery_date"] == sc1.expected["delivery_date"].isoformat()
    assert Decimal(first_oil["quantity"]) == sc1.expected["quantity"]
    assert Decimal(first_oil["unit_price"]) == sc1.expected["unit_price"]
    assert Decimal(first_oil["total_cost"]) == sc1.expected["total_cost"]
    assert (
        Decimal(first_oil["metrics"]["average_daily_consumption"])
        == sc1.expected["average_daily_consumption"]
    )
    assert Decimal(first_oil["metrics"]["initial_stock"]) == sc1.expected["initial_stock"]
    assert Decimal(plan_budget["known_total"]) == sc1.expected["budget_known_total"]


def verify_short_scenario(
    fc_short: dict[str, Any],
    alerts_items: list[dict[str, Any]],
) -> None:
    """Сверка сценария 6: short-history."""
    sc6 = get_demo_scenario("short-history")
    assert fc_short["is_history_complete"] is sc6.expected["is_history_complete"]
    assert fc_short["history_days"] == sc6.expected["history_days"]
    assert (
        Decimal(fc_short["average_daily_consumption"]) == sc6.expected["average_daily_consumption"]
    )
    assert Decimal(fc_short["recommended_qty"]) == sc6.expected["recommended_qty"]

    short_alert = next(
        a
        for a in alerts_items
        if a["sku"] == sc6.expected["sku"] and a["type"] == sc6.expected["alert_type"]
    )
    assert short_alert["metrics"]["history_days"] == sc6.expected["alert_history_days"]
    assert short_alert["metrics"]["required_days"] == sc6.expected["alert_required_days"]


def verify_noprice_scenario(
    plan_items: list[dict[str, Any]],
    plan_budget: dict[str, Any],
) -> None:
    """Сверка сценария 7: unknown-price."""
    sc7 = get_demo_scenario("unknown-price")
    noprice_items = [
        it
        for it in plan_items
        if it["sku"] == sc7.selector["sku"] and it["location"] == sc7.selector["location"]
    ]
    assert len(noprice_items) > 0
    first_noprice = noprice_items[0]
    assert Decimal(first_noprice["quantity"]) == sc7.expected["quantity"]
    assert first_noprice["unit_price"] is sc7.expected["unit_price"]
    assert first_noprice["total_cost"] is sc7.expected["total_cost"]
    assert plan_budget["is_price_complete"] is sc7.expected["budget_is_price_complete"]
    assert plan_budget["unknown_price_count"] >= sc7.expected["budget_unknown_price_count"]


def verify_nolead_scenario(
    plan_items: list[dict[str, Any]],
    plan_budget: dict[str, Any],
    plan_explanation: dict[str, Any],
) -> None:
    """Сверка сценария 8: unknown-lead-time."""
    sc8 = get_demo_scenario("unknown-lead-time")
    nolead_items = [
        it
        for it in plan_items
        if it["sku"] == sc8.selector["sku"] and it["location"] == sc8.selector["location"]
    ]
    assert len(nolead_items) == 1
    nolead = nolead_items[0]
    assert nolead["is_undated"] is sc8.expected["is_undated"]
    assert nolead["order_date"] is sc8.expected["order_date"]
    assert Decimal(nolead["quantity"]) == sc8.expected["quantity"]
    assert nolead["unit_price"] is sc8.expected["unit_price"]
    assert nolead["total_cost"] is sc8.expected["total_cost"]
    assert plan_budget["undated"]["items_count"] == sc8.expected["undated_items_count"]
    assert (
        Decimal(plan_budget["undated"]["total_quantity"]) == sc8.expected["undated_total_quantity"]
    )
    assert any(sc8.expected["warning_keyword"] in w for w in nolead.get("warnings", []))
    assert any(
        sc8.expected["incompleteness_reason_keyword"] in r
        for r in plan_explanation["incompleteness_reasons"]
    )


def verify_incoming_scenario(
    plan_items: list[dict[str, Any]],
    existing_orders: list[dict[str, Any]],
) -> None:
    """Сверка сценария 9: incoming-order."""
    sc9 = get_demo_scenario("incoming-order")
    po_item = next(o for o in existing_orders if o["sku"] == sc9.selector["sku"])
    assert po_item["doc_number"] == sc9.expected["existing_order_doc"]
    assert Decimal(po_item["pending_qty"]) == sc9.expected["existing_order_qty"]
    assert po_item["expected_date"] == sc9.expected["existing_order_date"].isoformat()

    incoming_plan_items = [
        it
        for it in plan_items
        if it["sku"] == sc9.selector["sku"] and it["location"] == sc9.selector["location"]
    ]
    assert len(incoming_plan_items) > 0
    first_incoming = incoming_plan_items[0]
    assert first_incoming["order_date"] == sc9.expected["first_order_date"].isoformat()
    assert Decimal(first_incoming["quantity"]) == sc9.expected["first_order_quantity"]


def normalize_item_for_comparison(item: dict[str, Any]) -> tuple:
    """Извлекает нормализованный предметный кортеж без суррогатных ID."""
    return (
        item["sku"],
        item["location"],
        item["order_date"],
        item.get("delivery_date"),
        item.get("is_undated", False),
        Decimal(str(item["quantity"])) if item.get("quantity") is not None else None,
        Decimal(str(item["unit_price"])) if item.get("unit_price") is not None else None,
        Decimal(str(item["total_cost"])) if item.get("total_cost") is not None else None,
    )
