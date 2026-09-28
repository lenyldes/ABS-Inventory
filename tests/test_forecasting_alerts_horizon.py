"""Тесты движения, истории, горизонта и валидации предупреждений (задача 3.1)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.forecasting.alerts import calculate_item_alerts
from app.inventory.domain import MovementSnapshot
from tests.alerts_fixtures import (
    BASE_AS_OF,
    make_test_balance,
    make_test_batch_stock,
    make_test_movements,
    make_test_procurement,
)


def test_alert_writeoff_risk_fefo() -> None:
    """Риск списания по FEFO: партия не успеет израсходоваться до срока годности."""
    batch = make_test_batch_stock(
        batch_id=301,
        batch_number="B-RISK",
        expiry_date=BASE_AS_OF + timedelta(days=10),
        available_quantity=Decimal("10.000"),
        current_quantity=Decimal("10.000"),
    )
    balance = make_test_balance(
        current_stock=Decimal("10.000"),
        available_stock=Decimal("10.000"),
        batches=(batch,),
    )
    movements = make_test_movements(total_consume_90d=Decimal("45.000"))  # a = 0.500000
    proc = make_test_procurement(lead_time_days=5)

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    writeoff = [a for a in alerts if a.type == "writeoff_risk"]

    assert len(writeoff) == 1
    item = writeoff[0]
    assert item.level == "warning"
    assert item.metrics["expected_writeoff_qty"] == "5.000"
    assert item.metrics["horizon_days"] == 30


def test_alert_no_movement() -> None:
    """Отсутствие расхода за пороговый период при наличии остатка."""
    balance = make_test_balance(current_stock=Decimal("8.000"), available_stock=Decimal("8.000"))
    movements = [
        MovementSnapshot(
            operation_date=BASE_AS_OF - timedelta(days=100),
            item_id=1,
            location_id=1,
            type="consume",
            quantity=Decimal("5.000"),
            doc_number="DOC-OLD",
            id=1,
        )
    ]
    proc = make_test_procurement(lead_time_days=5)

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    no_mov = [a for a in alerts if a.type == "no_movement"]

    assert len(no_mov) == 1
    assert no_mov[0].level == "info"
    assert no_mov[0].metrics["current_stock"] == "8.000"
    assert no_mov[0].metrics["no_movement_days_threshold"] == 90


def test_alert_incomplete_history() -> None:
    """Неполная история потребления (первое движение 25 дней назад)."""
    balance = make_test_balance(current_stock=Decimal("0.000"), available_stock=Decimal("0.000"))
    movements = make_test_movements(history_days=25, total_consume_90d=Decimal("25.000"))
    proc = make_test_procurement(lead_time_days=5)

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    incomp = [a for a in alerts if a.type == "incomplete_history"]

    assert len(incomp) == 1
    assert incomp[0].level == "info"
    assert incomp[0].metrics["history_days"] == 25
    assert incomp[0].metrics["required_days"] == 90


def test_alert_dynamic_and_explicit_horizon() -> None:
    """Динамический горизонт max(30, L + 1) и явный horizon_days."""
    balance = make_test_balance(current_stock=Decimal("0.000"), available_stock=Decimal("0.000"))
    movements = make_test_movements(total_consume_90d=Decimal("90.000"))

    # L = 45 -> horizon = max(30, 46) = 46 дней
    proc_long = make_test_procurement(lead_time_days=45)
    alerts_long = calculate_item_alerts(
        "OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc_long
    )
    st_long = next(a for a in alerts_long if a.type == "stockout")
    assert st_long.metrics["horizon_days"] == 46
    assert st_long.metrics["horizon_end"] == (BASE_AS_OF + timedelta(days=46)).isoformat()

    # Явный horizon_days = 7 при L = 45
    alerts_7 = calculate_item_alerts(
        "OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc_long, horizon_days=7
    )
    st_7 = next(a for a in alerts_7 if a.type == "stockout")
    assert st_7.metrics["horizon_days"] == 7
    assert st_7.metrics["horizon_end"] == (BASE_AS_OF + timedelta(days=7)).isoformat()


def test_alert_unknown_lead_time() -> None:
    """Неизвестный срок поставки L is None: дефолт 30 дней, отсутствие ложного дефицита."""
    batch = make_test_batch_stock(
        batch_id=1,
        available_quantity=Decimal("10.000"),
        current_quantity=Decimal("10.000"),
    )
    balance = make_test_balance(
        current_stock=Decimal("10.000"),
        available_stock=Decimal("10.000"),
        batches=(batch,),
    )
    movements = make_test_movements(total_consume_90d=Decimal("90.000"))
    proc_unknown = make_test_procurement(lead_time_days=None)

    alerts = calculate_item_alerts(
        "OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc_unknown
    )
    assert not any(a.type == "stockout" for a in alerts)
    assert not any(a.type == "potential_stockout" for a in alerts)


def test_unknown_lead_time_is_explained_in_forecast_alerts() -> None:
    """Дефицит и риск списания раскрывают ограничение при неизвестном сроке поставки."""
    movements = make_test_movements(total_consume_90d=Decimal("45.000"))
    procurement = make_test_procurement(lead_time_days=None)
    empty_balance = make_test_balance(current_stock=Decimal("0"), available_stock=Decimal("0"))

    stockout_alerts = calculate_item_alerts(
        "OIL-500", "MSK-01", BASE_AS_OF, empty_balance, movements, procurement
    )
    stockout = next(alert for alert in stockout_alerts if alert.type == "stockout")
    assert stockout.metrics["horizon_days"] == 30
    assert stockout.metrics["horizon_end"] == (BASE_AS_OF + timedelta(days=30)).isoformat()
    assert "Срок поставки не задан" in stockout.metrics["calculation_limit"]
    assert "30 дней" in stockout.metrics["calculation_limit"]

    batch = make_test_batch_stock(
        expiry_date=BASE_AS_OF + timedelta(days=10),
        current_quantity=Decimal("10.000"),
        available_quantity=Decimal("10.000"),
    )
    balance = make_test_balance(batches=(batch,))
    writeoff_alerts = calculate_item_alerts(
        "OIL-500", "MSK-01", BASE_AS_OF, balance, movements, procurement
    )
    writeoff = next(alert for alert in writeoff_alerts if alert.type == "writeoff_risk")
    assert writeoff.metrics["horizon_days"] == 30
    assert writeoff.metrics["calculation_limit"] == stockout.metrics["calculation_limit"]
    assert all(
        "calculation_limit" not in alert.metrics
        for alert in writeoff_alerts
        if alert.type == "expiring_soon"
    )


def test_explicit_horizon_with_unknown_lead_time_keeps_limitation() -> None:
    """Явный горизонт не скрывает невозможность оценить срок прибытия."""
    balance = make_test_balance(current_stock=Decimal("0"), available_stock=Decimal("0"))
    alerts = calculate_item_alerts(
        "OIL-500",
        "MSK-01",
        BASE_AS_OF,
        balance,
        make_test_movements(),
        make_test_procurement(lead_time_days=None),
        horizon_days=7,
    )
    stockout = next(alert for alert in alerts if alert.type == "stockout")
    assert stockout.metrics["horizon_days"] == 7
    assert "Срок поставки не задан" in stockout.metrics["calculation_limit"]
    assert "30 дней" not in stockout.metrics["calculation_limit"]


def test_alert_threshold_validations() -> None:
    """Ошибки валидации при некорректных порогах и горизонте."""
    balance = make_test_balance()
    movements = make_test_movements()
    proc = make_test_procurement()

    with pytest.raises(ValueError, match="horizon_days"):
        calculate_item_alerts("SKU", "LOC", BASE_AS_OF, balance, movements, proc, horizon_days=0)

    with pytest.raises(ValueError, match="shelf_life_days_threshold"):
        calculate_item_alerts(
            "SKU", "LOC", BASE_AS_OF, balance, movements, proc, shelf_life_days_threshold=0
        )

    with pytest.raises(ValueError, match="no_movement_days_threshold"):
        calculate_item_alerts(
            "SKU", "LOC", BASE_AS_OF, balance, movements, proc, no_movement_days_threshold=0
        )
