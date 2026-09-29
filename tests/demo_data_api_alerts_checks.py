"""Вспомогательные проверки сценариев склада и предупреждений в тестах demo-data."""

from decimal import Decimal
from typing import Any

from app.demo_data.scenarios import get_demo_scenario


def verify_deficit_scenario(alerts_items: list[dict[str, Any]]) -> None:
    """Сверка сценария 2: lead-time-stockout."""
    sc2 = get_demo_scenario("lead-time-stockout")
    def_alert = next(
        a
        for a in alerts_items
        if a["sku"] == sc2.selector["sku"]
        and a["location"] == sc2.selector["location"]
        and a["type"] == sc2.selector["type"]
    )
    assert def_alert["level"] == sc2.expected["level"]
    assert def_alert["metrics"]["stockout_date"] == sc2.expected["stockout_date"].isoformat()
    assert Decimal(def_alert["metrics"]["days_of_stock"]) == sc2.expected["days_of_stock"]
    assert def_alert["metrics"]["lead_time_days"] == sc2.expected["lead_time_days"]
    assert Decimal(def_alert["metrics"]["available_stock"]) == sc2.expected["available_stock"]


def verify_expiry_scenario(alerts_items: list[dict[str, Any]]) -> None:
    """Сверка сценария 3: expiry-and-writeoff."""
    sc3 = get_demo_scenario("expiry-and-writeoff")
    writeoff_alert = next(
        a
        for a in alerts_items
        if a["sku"] == sc3.selector["sku"]
        and a["location"] == sc3.selector["location"]
        and a["type"] == sc3.selector["type"]
    )
    assert writeoff_alert["level"] == sc3.expected["level"]
    assert (
        Decimal(writeoff_alert["metrics"]["expected_writeoff_qty"])
        == sc3.expected["expected_writeoff_qty"]
    )
    assert writeoff_alert["metrics"]["horizon_days"] == sc3.expected["horizon_days"]

    expiring_alert = next(
        a
        for a in alerts_items
        if a["sku"] == sc3.selector["sku"] and a["type"] == sc3.expected["expiring_soon_type"]
    )
    assert expiring_alert["level"] == sc3.expected["expiring_soon_level"]
    assert (
        expiring_alert["metrics"]["days_until_expiry"]
        == sc3.expected["expiring_soon_days_until_expiry"]
    )
    assert (
        expiring_alert["metrics"]["expiry_date"]
        == sc3.expected["expiring_soon_expiry_date"].isoformat()
    )
    assert expiring_alert["metrics"]["batch_number"] == sc3.expected["expiring_soon_batch_number"]


def verify_expired_scenario(
    stock_items: list[dict[str, Any]],
    alerts_items: list[dict[str, Any]],
) -> None:
    """Сверка сценария 4: expired-stock."""
    sc4 = get_demo_scenario("expired-stock")
    exp_stock = next(
        s
        for s in stock_items
        if s["sku"] == sc4.selector["sku"] and s["location"] == sc4.selector["location"]
    )
    assert Decimal(exp_stock["current_stock"]) == sc4.expected["current_stock"]
    assert Decimal(exp_stock["available_stock"]) == sc4.expected["available_stock"]
    assert Decimal(exp_stock["expired_stock"]) == sc4.expected["expired_stock"]
    assert exp_stock["days_of_stock"] is sc4.expected["days_of_stock"]

    expired_alert = next(
        a
        for a in alerts_items
        if a["sku"] == sc4.selector["sku"] and a["type"] == sc4.expected["alert_type"]
    )
    assert expired_alert["level"] == sc4.expected["alert_level"]
    assert (
        Decimal(expired_alert["metrics"]["expired_quantity"])
        == sc4.expected["alert_expired_quantity"]
    )


def verify_idle_scenario(
    alerts_items: list[dict[str, Any]],
    plan_items: list[dict[str, Any]],
) -> None:
    """Сверка сценария 5: no-movement."""
    sc5 = get_demo_scenario("no-movement")
    idle_alert = next(
        a
        for a in alerts_items
        if a["sku"] == sc5.selector["sku"]
        and a["location"] == sc5.selector["location"]
        and a["type"] == sc5.selector["type"]
    )
    assert idle_alert["level"] == sc5.expected["level"]
    assert Decimal(idle_alert["metrics"]["current_stock"]) == sc5.expected["current_stock"]
    idle_plan_items = [it for it in plan_items if it["sku"] == sc5.selector["sku"]]
    assert len(idle_plan_items) == sc5.expected["plan_items_count"]
