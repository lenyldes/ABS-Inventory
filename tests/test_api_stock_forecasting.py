"""HTTP-тесты показателей расхода и дней запаса в эндпоинте GET /api/stock."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import (
    register_consume,
    register_receipt,
    register_return,
)
from app.main import app
from app.models.catalog import Item, Location


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


def test_stock_summary_with_consumption_and_days_of_stock(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка возврата среднего расхода и дней запаса при наличии расхода и их согласованности."""
    item = Item(sku="FC-OIL-01", name="Масло лаванды", category="Масла", unit="л")
    loc = Location(code="FC-LOC-01", name="SPA Центр")
    db_session.add_all([item, loc])
    db_session.commit()

    # Поступление 100 л
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 6, 1),
        quantity=Decimal("100.000"),
        doc_number="REC-01",
        batch_number="B-01",
        expiry_date=date(2027, 6, 1),
        unit_price=Decimal("150.00"),
    )
    # Расход 18 л внутри 90-дневного окна относительно 2026-09-01
    register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("18.000"),
        doc_number="CON-01",
    )
    db_session.commit()

    as_of = date(2026, 9, 1)
    resp = client.get(f"/api/stock?sku=FC-OIL-01&as_of={as_of.isoformat()}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] == 1
    row = data["items"][0]

    assert row["sku"] == "FC-OIL-01"
    assert row["location"] == "FC-LOC-01"
    assert row["current_stock"] == "82.000"
    assert row["available_stock"] == "82.000"
    assert row["expired_stock"] == "0.000"

    # Расход 18 / 90 = 0.200000
    assert row["average_daily_consumption"] == "0.200000"
    # Дни запаса: 82 / 0.2 = 410.0
    assert row["days_of_stock"] == "410.0"

    # Проверка согласованности: available_stock / average_daily_consumption == days_of_stock
    avail = Decimal(row["available_stock"])
    avg_cons = Decimal(row["average_daily_consumption"])
    expected_days = (avail / avg_cons).quantize(Decimal("0.1"))
    assert Decimal(row["days_of_stock"]) == expected_days


def test_stock_summary_zero_consumption(
    client: TestClient,
    db_session: Session,
) -> None:
    """При отсутствии расхода средний расход равен 0.000000, а дни запаса null."""
    item = Item(sku="FC-OIL-02", name="Масло розы", category="Масла", unit="л")
    loc = Location(code="FC-LOC-02", name="SPA Север")
    db_session.add_all([item, loc])
    db_session.commit()

    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("25.000"),
        doc_number="REC-02",
        batch_number="B-02",
        expiry_date=date(2027, 8, 1),
        unit_price=Decimal("500.00"),
    )
    db_session.commit()

    resp = client.get("/api/stock?sku=FC-OIL-02&as_of=2026-09-01")
    assert resp.status_code == 200

    row = resp.json()["items"][0]
    assert row["current_stock"] == "25.000"
    assert row["available_stock"] == "25.000"
    assert row["average_daily_consumption"] == "0.000000"
    assert row["days_of_stock"] is None


def test_stock_summary_with_consumption_and_returns(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка учёта возврата при расчёте среднего расхода и дней запаса."""
    item = Item(sku="FC-OIL-03", name="Масло мяты", category="Масла", unit="л")
    loc = Location(code="FC-LOC-03", name="SPA Запад")
    db_session.add_all([item, loc])
    db_session.commit()

    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 7, 1),
        quantity=Decimal("50.000"),
        doc_number="REC-03",
        batch_number="B-03",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("120.00"),
    )
    consume_res = register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 7, 10),
        quantity=Decimal("20.000"),
        doc_number="CON-03",
    )
    # Возврат 5.000 по исходной выдаче
    register_return(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 7, 15),
        quantity=Decimal("5.000"),
        doc_number="RET-03",
        parent_movement_id=consume_res.movement.id,
        parent_allocation_id=consume_res.allocations[0].id,
    )
    db_session.commit()

    resp = client.get("/api/stock?sku=FC-OIL-03&as_of=2026-08-01")
    assert resp.status_code == 200

    row = resp.json()["items"][0]
    # Чистый расход = 20 - 5 = 15. 15 / 90 = 0.166667
    assert row["average_daily_consumption"] == "0.166667"
    # Остаток = 50 - 20 + 5 = 35
    assert row["available_stock"] == "35.000"
    # Дни запаса: 35 / 0.166667 = 210.0
    assert row["days_of_stock"] == "210.0"

    avail = Decimal(row["available_stock"])
    avg_cons = Decimal(row["average_daily_consumption"])
    expected_days = (avail / avg_cons).quantize(Decimal("0.1"))
    assert Decimal(row["days_of_stock"]) == expected_days


def test_stock_summary_days_of_stock_uses_available_stock_not_current(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка расчёта дней запаса от доступного остатка, исключая просроченный."""
    item = Item(sku="FC-OIL-04", name="Масло мелиссы", category="Масла", unit="л")
    loc = Location(code="FC-LOC-04", name="SPA Загород")
    db_session.add_all([item, loc])
    db_session.commit()

    # Просроченная партия на 2026-09-01
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 7, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-EXP",
        batch_number="B-EXP",
        expiry_date=date(2026, 8, 15),
        unit_price=Decimal("100.00"),
    )
    # Годная партия
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 7, 1),
        quantity=Decimal("20.000"),
        doc_number="REC-GOOD",
        batch_number="B-GOOD",
        expiry_date=date(2026, 12, 31),
        unit_price=Decimal("100.00"),
    )
    # Расход 5 л 2026-08-01 (спишет из годной/первой партии)
    register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("5.000"),
        doc_number="CON-04",
    )
    db_session.commit()

    resp = client.get("/api/stock?sku=FC-OIL-04&as_of=2026-09-01")
    assert resp.status_code == 200

    row = resp.json()["items"][0]
    assert row["current_stock"] == "25.000"
    assert row["available_stock"] == "20.000"
    assert row["expired_stock"] == "5.000"

    # Расход 5 / 90 = 0.055556
    assert row["average_daily_consumption"] == "0.055556"
    # Дни запаса от available_stock (20.000), а не от current_stock (25.000):
    # 20 / 0.055556 = 360.0 (при current_stock было бы 450.0)
    assert row["days_of_stock"] == "360.0"

    avail = Decimal(row["available_stock"])
    avg_cons = Decimal(row["average_daily_consumption"])
    expected_days = (avail / avg_cons).quantize(Decimal("0.1"))
    assert Decimal(row["days_of_stock"]) == expected_days
