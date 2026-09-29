"""Тесты каталога контрольных сценариев демонстрационного набора (задача 3.1)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from app.demo_data.scenarios import (
    DEMO_SCENARIO_IDS,
    DEMO_SCENARIOS,
    DEMO_SCENARIOS_BY_ID,
    get_demo_scenario,
)

EXPECTED_SCENARIO_IDS: set[str] = {
    "oil-quarter-plan",
    "lead-time-stockout",
    "expiry-and-writeoff",
    "expired-stock",
    "no-movement",
    "short-history",
    "unknown-price",
    "unknown-lead-time",
    "incoming-order",
}

EXPECTED_API_PATHS: set[str] = {
    "/api/stock",
    "/api/forecast",
    "/api/alerts",
    "/api/procurement/plan",
}

SURROGATE_ID_KEYS: set[str] = {
    "id",
    "batch_id",
    "item_id",
    "location_id",
    "supplier_pk",
    "order_id",
}


def test_demo_scenarios_completeness() -> None:
    """Проверяет полноту каталога: ровно 9 сценариев со стабильными ID из design.md."""
    assert len(DEMO_SCENARIOS) == 9
    assert DEMO_SCENARIO_IDS == EXPECTED_SCENARIO_IDS
    assert set(DEMO_SCENARIOS_BY_ID.keys()) == EXPECTED_SCENARIO_IDS

    for sc in DEMO_SCENARIOS:
        assert isinstance(sc.name, str) and len(sc.name.strip()) > 0
        assert isinstance(sc.goal, str) and len(sc.goal.strip()) > 0
        assert sc.id == get_demo_scenario(sc.id).id

    with pytest.raises(KeyError, match="Неизвестный сценарий"):
        get_demo_scenario("non-existent-scenario")


def test_demo_scenarios_four_apis_covered() -> None:
    """Проверяет покрытие параметров четырёх ключевых API и наличие контрольной даты."""
    observed_paths = {sc.path for sc in DEMO_SCENARIOS}
    assert observed_paths == EXPECTED_API_PATHS

    for sc in DEMO_SCENARIOS:
        assert sc.method in {"GET", "POST"}
        if sc.method == "GET":
            assert sc.params is not None
            assert sc.params.get("as_of") == "2026-09-29"
            if sc.path == "/api/stock":
                assert sc.params.get("limit") == 100
        elif sc.method == "POST":
            assert sc.json_body is not None
            assert sc.json_body.get("as_of") == "2026-09-29"


def test_demo_scenarios_expectations_independent_of_internal_ids() -> None:
    """Проверяет независимость эталонов и селекторов от суррогатных первичных ключей БД."""
    for sc in DEMO_SCENARIOS:
        # Селектор не должен опираться на внутренние первичные ключи
        if sc.selector:
            for key in sc.selector:
                assert key not in SURROGATE_ID_KEYS, (
                    f"Сценарий {sc.id} использует суррогатный ключ {key} в selector"
                )
                assert key in {
                    "sku",
                    "location",
                    "type",
                    "doc_number",
                }, f"Неожиданное поле {key} в selector сценария {sc.id}"

        # Ожидания эталонов не должны требовать внутренних ID
        for key, val in sc.expected.items():
            assert key not in SURROGATE_ID_KEYS, (
                f"Сценарий {sc.id} использует суррогатный ключ {key} в expected"
            )
            # Значения не должны быть исполняемыми функциями (расчётами в рантайме)
            assert not isinstance(val, Callable), (
                f"Ожидание {key} в {sc.id} является функцией, а не литералом"
            )
            # Значения должны быть простыми литералами или датами/Decimal
            assert isinstance(val, (int, float, str, bool, Decimal, date, type(None), dict, list))

    # Специфические литеральные константы для DEMO-OIL
    oil_sc = get_demo_scenario("oil-quarter-plan")
    assert oil_sc.expected["average_daily_consumption"] == Decimal("1.000000")
    assert oil_sc.expected["initial_stock"] == Decimal("50.000")
    assert oil_sc.expected["quantity"] == Decimal("30.000")
    assert oil_sc.expected["unit_price"] == Decimal("100.00")
    assert oil_sc.expected["total_cost"] == Decimal("3000.00")
    assert oil_sc.expected["order_date"] == date(2026, 11, 11)
    assert oil_sc.expected["budget_known_total"] == Decimal("20300.00")

    assert oil_sc.forecast_expected is not None
    assert oil_sc.forecast_expected["current_stock"] == Decimal("50.000")
    assert oil_sc.forecast_expected["average_daily_consumption"] == Decimal("1.000000")

    assert oil_sc.stock_expected is not None
    assert oil_sc.stock_expected["current_stock"] == Decimal("50.000")
    assert oil_sc.stock_expected["average_daily_consumption"] == Decimal("1.000000")
