"""Тесты предупреждений о дефиците и сроках годности (задача 3.1)."""

from datetime import timedelta
from decimal import Decimal

from app.forecasting.alerts import calculate_item_alerts
from app.forecasting.domain import IncomingOrderSnapshot
from tests.alerts_fixtures import (
    BASE_AS_OF,
    make_test_balance,
    make_test_batch_stock,
    make_test_movements,
    make_test_procurement,
)


def test_alert_stockout_zero_stock() -> None:
    """Критический дефицит при нулевом доступном запасе и наличии потребления."""
    balance = make_test_balance(
        current_stock=Decimal("0.000"),
        available_stock=Decimal("0.000"),
    )
    movements = make_test_movements(total_consume_90d=Decimal("90.000"))
    proc = make_test_procurement(lead_time_days=5)

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    stockouts = [a for a in alerts if a.type == "stockout"]

    assert len(stockouts) == 1
    item = stockouts[0]
    assert item.level == "critical"
    assert item.id == f"alert-stockout-MSK-01-OIL-500-{BASE_AS_OF.isoformat()}"
    assert item.metrics["available_stock"] == "0.000"
    assert item.metrics["average_daily_consumption"] == "1.000000"
    assert item.metrics["lead_time_days"] == 5
    assert item.metrics["days_of_stock"] == "0.0"
    assert item.metrics["horizon_days"] == 30


def test_alert_stockout_depletion_before_arrival() -> None:
    """Критический дефицит: исчерпание запаса до возможного прибытия заказа."""
    batch = make_test_batch_stock(
        batch_id=1,
        available_quantity=Decimal("4.000"),
        current_quantity=Decimal("4.000"),
    )
    balance = make_test_balance(
        current_stock=Decimal("4.000"),
        available_stock=Decimal("4.000"),
        batches=(batch,),
    )
    movements = make_test_movements(total_consume_90d=Decimal("90.000"))
    proc = make_test_procurement(lead_time_days=7)

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    stockouts = [a for a in alerts if a.type == "stockout"]

    assert len(stockouts) == 1
    assert stockouts[0].level == "critical"
    assert stockouts[0].metrics["available_stock"] == "4.000"
    assert stockouts[0].metrics["days_of_stock"] == "4.0"
    assert "stockout_date" in stockouts[0].metrics


def test_alert_stockout_supply_after_depletion() -> None:
    """Риск дефицита при исчерпании до поставки (даже если заказ покрывает весь горизонт)."""
    batch = make_test_batch_stock(
        batch_id=1,
        available_quantity=Decimal("2.000"),
        current_quantity=Decimal("2.000"),
    )
    balance = make_test_balance(
        current_stock=Decimal("2.000"),
        available_stock=Decimal("2.000"),
        batches=(batch,),
    )
    movements = make_test_movements(total_consume_90d=Decimal("90.000"))
    incoming = IncomingOrderSnapshot(
        order_id=10,
        doc_number="PO-10",
        expected_date=BASE_AS_OF + timedelta(days=5),
        pending_qty=Decimal("100.000"),
    )
    proc = make_test_procurement(lead_time_days=5, pending_orders=(incoming,))

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    stockouts = [a for a in alerts if a.type == "stockout"]
    assert len(stockouts) == 1
    assert stockouts[0].level == "critical"


def test_alert_stockout_delayed_order_does_not_mask() -> None:
    """Задержанная поставка (expected_date <= as_of) не маскирует дефицит."""
    balance = make_test_balance(
        current_stock=Decimal("0.000"),
        available_stock=Decimal("0.000"),
    )
    movements = make_test_movements(total_consume_90d=Decimal("90.000"))
    delayed = IncomingOrderSnapshot(
        order_id=11,
        doc_number="PO-DELAYED",
        expected_date=BASE_AS_OF - timedelta(days=2),
        pending_qty=Decimal("50.000"),
    )
    proc = make_test_procurement(lead_time_days=5, delayed_orders=(delayed,))

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    stockouts = [a for a in alerts if a.type == "stockout"]
    assert len(stockouts) == 1
    assert stockouts[0].level == "critical"


def test_alert_potential_stockout() -> None:
    """Потенциальный дефицит: available_stock < reorder_point, но order_date > as_of."""
    batch = make_test_batch_stock(
        batch_id=1,
        available_quantity=Decimal("5.000"),
        current_quantity=Decimal("5.000"),
    )
    balance = make_test_balance(
        current_stock=Decimal("5.000"),
        available_stock=Decimal("5.000"),
        batches=(batch,),
    )
    incoming = IncomingOrderSnapshot(
        order_id=20,
        doc_number="PO-20",
        expected_date=BASE_AS_OF + timedelta(days=2),
        pending_qty=Decimal("25.000"),
    )
    movements = make_test_movements(total_consume_90d=Decimal("90.000"))
    proc = make_test_procurement(lead_time_days=10, pending_orders=(incoming,))

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    potential = [a for a in alerts if a.type == "potential_stockout"]

    assert len(potential) == 1
    item = potential[0]
    assert item.level == "warning"
    assert item.metrics["available_stock"] == "5.000"
    assert item.metrics["reorder_point"] == "10.000"
    assert item.metrics["order_date"] > BASE_AS_OF.isoformat()


def test_alert_expired_batches() -> None:
    """Просроченный остаток на складе (critical, с указанием партии)."""
    expired_batch = make_test_batch_stock(
        batch_id=101,
        batch_number="B-EXP",
        expiry_date=BASE_AS_OF - timedelta(days=5),
        current_quantity=Decimal("7.000"),
        available_quantity=Decimal("0.000"),
        expired_quantity=Decimal("7.000"),
    )
    balance = make_test_balance(
        current_stock=Decimal("7.000"),
        available_stock=Decimal("0.000"),
        expired_stock=Decimal("7.000"),
        batches=(expired_batch,),
    )
    movements = make_test_movements(total_consume_90d=Decimal("0.000"))
    proc = make_test_procurement(lead_time_days=5)

    alerts = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    expired = [a for a in alerts if a.type == "expired"]

    assert len(expired) == 1
    item = expired[0]
    assert item.level == "critical"
    assert item.batch_id == 101
    assert item.id == f"alert-expired-MSK-01-OIL-500-101-{BASE_AS_OF.isoformat()}"
    assert item.metrics["days_overdue"] == 5
    assert item.metrics["expired_quantity"] == "7.000"


def test_alert_expiring_soon_thresholds() -> None:
    """Приближение срока годности по порогу и пограничные случаи."""
    b_exact_30 = make_test_batch_stock(
        batch_id=201,
        batch_number="B-30D",
        expiry_date=BASE_AS_OF + timedelta(days=30),
        available_quantity=Decimal("5.000"),
    )
    b_31d = make_test_batch_stock(
        batch_id=202,
        batch_number="B-31D",
        expiry_date=BASE_AS_OF + timedelta(days=31),
        available_quantity=Decimal("5.000"),
    )
    b_10d = make_test_batch_stock(
        batch_id=203,
        batch_number="B-10D",
        expiry_date=BASE_AS_OF + timedelta(days=10),
        available_quantity=Decimal("5.000"),
    )
    balance = make_test_balance(
        current_stock=Decimal("15.000"),
        available_stock=Decimal("15.000"),
        batches=(b_exact_30, b_31d, b_10d),
    )
    movements = make_test_movements(total_consume_90d=Decimal("0.000"))
    proc = make_test_procurement(lead_time_days=5)

    alerts_def = calculate_item_alerts("OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc)
    soon_def = [a for a in alerts_def if a.type == "expiring_soon"]
    assert {a.batch_id for a in soon_def} == {201, 203}

    alerts_14 = calculate_item_alerts(
        "OIL-500", "MSK-01", BASE_AS_OF, balance, movements, proc, shelf_life_days_threshold=14
    )
    soon_14 = [a for a in alerts_14 if a.type == "expiring_soon"]
    assert {a.batch_id for a in soon_14} == {203}
