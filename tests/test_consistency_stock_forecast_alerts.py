"""Сквозные тесты согласованности показателей /api/stock, /api/forecast и /api/alerts (задача 4.1).

Проверяет:
1. Согласованность available_stock, average_daily_consumption, days_of_stock,
   горизонта и даты дефицита на одной контрольной дате as_of.
2. Отсутствие побочных записей (side-effects) в таблицах movements, batches,
   purchase_orders, stock_locks при выполнении запросов на чтение.
"""

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
from app.models.inventory import Batch, Movement, StockLock
from app.models.procurement import PurchaseOrder
from tests.forecasting_fixtures import (
    make_purchase_order,
    make_supplier_condition,
)


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def test_stock_forecast_alerts_metrics_consistency(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Проверка совпадения расчётных показателей и дефицита на единой дате as_of."""
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 28)
    horizon_days = 30

    # Закупочные условия с lead_time_days = 15
    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        lead_time_days=15,
        package_size=Decimal("10.000"),
        min_order_qty=Decimal("10.000"),
        estimated_price=Decimal("150.00"),
    )

    # Приход 100 л годностью до конца года
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("100.000"),
        doc_number="REC-CONS-01",
        batch_number="B-CONS-01",
        expiry_date=date(2026, 12, 31),
        unit_price=Decimal("150.00"),
    )

    # Расход 90 л в окне 90 дней -> среднесуточный расход 90 / 90 = 1.000000 л/день
    # Доступный остаток = 10.000 л, запас на 10.0 дней
    # Исчерпание запаса: as_of + 10 дней = 2026-10-08
    # Срок поставки 15 дней > 10 дней -> критический дефицит (stockout)
    register_consume(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 8, 20),
        quantity=Decimal("90.000"),
        doc_number="CON-CONS-01",
    )
    db_session.commit()

    # 1. Запрос GET /api/stock
    resp_stock = client.get(
        "/api/stock",
        params={
            "sku": item.sku,
            "location": location.code,
            "as_of": as_of.isoformat(),
        },
    )
    assert resp_stock.status_code == 200, resp_stock.text
    stock_data = resp_stock.json()
    assert stock_data["total"] == 1
    stock_row = stock_data["items"][0]

    # 2. Запрос POST /api/forecast
    resp_forecast = client.post(
        "/api/forecast",
        json={
            "sku": item.sku,
            "location": location.code,
            "as_of": as_of.isoformat(),
            "horizon_days": horizon_days,
        },
    )
    assert resp_forecast.status_code == 200, resp_forecast.text
    forecast_data = resp_forecast.json()

    # 3. Запрос GET /api/alerts
    resp_alerts = client.get(
        "/api/alerts",
        params={
            "sku": item.sku,
            "location": location.code,
            "as_of": as_of.isoformat(),
            "horizon_days": horizon_days,
        },
    )
    assert resp_alerts.status_code == 200, resp_alerts.text
    alerts_data = resp_alerts.json()
    stockout_alerts = [a for a in alerts_data["items"] if a["type"] == "stockout"]
    assert len(stockout_alerts) == 1, f"Ожидался алерт stockout, получено: {alerts_data['items']}"
    stockout_metrics = stockout_alerts[0]["metrics"]

    # Проверка 1: available_stock совпадает в /api/stock, /api/forecast и в metrics /api/alerts
    stock_avail = Decimal(str(stock_row["available_stock"]))
    forecast_avail = Decimal(str(forecast_data["available_stock"]))
    alert_avail = Decimal(str(stockout_metrics["available_stock"]))
    assert stock_avail == forecast_avail == alert_avail == Decimal("10.000")

    # Проверка 2: average_daily_consumption совпадает во всех трёх эндпоинтах
    stock_avg = Decimal(str(stock_row["average_daily_consumption"]))
    forecast_avg = Decimal(str(forecast_data["average_daily_consumption"]))
    alert_avg = Decimal(str(stockout_metrics["average_daily_consumption"]))
    assert stock_avg == forecast_avg == alert_avg == Decimal("1.000000")

    # Проверка 3: days_of_stock совпадает в /api/stock и в metrics /api/alerts
    stock_dos = Decimal(str(stock_row["days_of_stock"]))
    alert_dos = Decimal(str(stockout_metrics["days_of_stock"]))
    assert stock_dos == alert_dos == Decimal("10.0")

    # Проверка 4: горизонт и дефицит согласованы между /api/forecast и /api/alerts
    assert forecast_data["days_count"] == horizon_days
    assert stockout_metrics["horizon_days"] == horizon_days
    assert forecast_data["horizon_end"] == stockout_metrics["horizon_end"] == "2026-10-28"

    assert forecast_data["stockout_date"] == "2026-10-08"
    assert stockout_metrics["stockout_date"] == "2026-10-08"
    assert forecast_data["stockout_date"] == stockout_metrics["stockout_date"]


def test_no_side_effects_on_read_endpoints(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Проверка строгого отсутствия записей при чтении во всех таблицах склада и закупок."""
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 28)

    # Заполняем таблицы данными: партии, движения, заказы (блокировка создаётся при операциях)
    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        lead_time_days=7,
        package_size=Decimal("5.000"),
        min_order_qty=Decimal("5.000"),
    )
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("50.000"),
        doc_number="REC-NO-SE-01",
        batch_number="B-NO-SE-01",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("80.00"),
    )
    register_consume(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("10.000"),
        doc_number="CON-NO-SE-01",
    )
    make_purchase_order(
        db_session,
        item.id,
        location.id,
        supplier.id,
        doc_number="PO-NO-SE-01",
        expected_date=date(2026, 10, 15),
        expected_qty=Decimal("20.000"),
        unit_price=Decimal("80.00"),
    )
    db_session.commit()

    def get_table_counts() -> dict[str, int]:
        return {
            "movements": db_session.query(Movement).count(),
            "batches": db_session.query(Batch).count(),
            "purchase_orders": db_session.query(PurchaseOrder).count(),
            "stock_locks": db_session.query(StockLock).count(),
        }

    counts_before = get_table_counts()
    # Убеждаемся, что в каждой отслеживаемой таблице есть хотя бы одна запись
    for table_name, count in counts_before.items():
        assert count > 0, f"Таблица {table_name} должна содержать тестовые данные"

    # Выполняем запросы ко всем эндпоинтам чтения
    res_stock = client.get("/api/stock", params={"as_of": as_of.isoformat()})
    assert res_stock.status_code == 200

    res_stock_sku = client.get(f"/api/stock/{item.sku}", params={"as_of": as_of.isoformat()})
    assert res_stock_sku.status_code == 200

    res_forecast = client.post(
        "/api/forecast",
        json={
            "sku": item.sku,
            "location": location.code,
            "as_of": as_of.isoformat(),
            "horizon_days": 30,
        },
    )
    assert res_forecast.status_code == 200

    res_alerts = client.get("/api/alerts", params={"as_of": as_of.isoformat()})
    assert res_alerts.status_code == 200

    res_alerts_filtered = client.get(
        "/api/alerts",
        params={
            "sku": item.sku,
            "location": location.code,
            "as_of": as_of.isoformat(),
            "horizon_days": 30,
        },
    )
    assert res_alerts_filtered.status_code == 200

    counts_after = get_table_counts()

    assert counts_before == counts_after, (
        f"Обнаружены побочные изменения данных при чтении: "
        f"было {counts_before}, стало {counts_after}"
    )
