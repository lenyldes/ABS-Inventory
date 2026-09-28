"""HTTP-тесты сводных и детальных остатков: GET /api/stock и GET /api/stock/{sku}."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import register_consume, register_receipt
from app.main import app
from app.models.catalog import Item, Location


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


def test_get_stock_summary_and_null_metrics(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка сводного остатка, валидации пагинации и null у показателей этапа 07."""
    item = Item(sku="OIL-STK-01", name="Масло чайного дерева", category="Масла", unit="л")
    loc = Location(code="LOC-STK-01", name="SPA Восток")
    db_session.add_all([item, loc])
    db_session.commit()

    # Проверка валидации пагинации
    r_bad_limit = client.get("/api/stock?limit=0")
    assert r_bad_limit.status_code == 400
    assert r_bad_limit.json()["code"] == "INVALID_PAGINATION"

    # Регистрация поступления
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="DOC-STK-REC1",
        batch_number="B-STK-1",
        expiry_date=date(2026, 12, 31),
        unit_price=Decimal("200.00"),
    )
    db_session.commit()

    resp = client.get("/api/stock")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    row = data["items"][0]
    assert row["sku"] == "OIL-STK-01"
    assert row["location"] == "LOC-STK-01"
    assert row["current_stock"] == "10.000"
    assert row["available_stock"] == "10.000"
    assert row["expired_stock"] == "0.000"
    assert row["nearest_expiry_date"] == "2026-12-31"
    # Показатели этапа 07 обязаны быть null
    assert row["average_daily_consumption"] is None
    assert row["days_of_stock"] is None


def test_get_stock_locations_independence(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка изолированности и независимости остатков по разным объектам."""
    item = Item(sku="OIL-IND-01", name="Масло эвкалипта", category="Масла", unit="л")
    loc1 = Location(code="LOC-IND-01", name="Объект 1")
    loc2 = Location(code="LOC-IND-02", name="Объект 2")
    db_session.add_all([item, loc1, loc2])
    db_session.commit()

    # Приход 10 на объект 1 и 5 на объект 2
    register_receipt(
        db_session,
        item=item,
        location=loc1,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="DOC-IND-1",
        batch_number="B-IND-1",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    register_receipt(
        db_session,
        item=item,
        location=loc2,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="DOC-IND-2",
        batch_number="B-IND-2",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    # Расход 3 на объекте 1
    register_consume(
        db_session,
        item=item,
        location=loc1,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("3.000"),
        doc_number="DOC-IND-3",
    )
    db_session.commit()

    # Проверяем фильтрацию по location
    r_loc1 = client.get("/api/stock?location=LOC-IND-01")
    assert r_loc1.status_code == 200
    assert r_loc1.json()["items"][0]["current_stock"] == "7.000"

    r_loc2 = client.get("/api/stock?location=LOC-IND-02")
    assert r_loc2.status_code == 200
    assert r_loc2.json()["items"][0]["current_stock"] == "5.000"


def test_get_stock_expiration_calculation(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка разделения учётного, доступного и просроченного остатка."""
    item = Item(sku="CREAM-EXP-01", name="Крем для лица", category="Кремы", unit="шт")
    loc = Location(code="LOC-EXP-01", name="SPA Юг")
    db_session.add_all([item, loc])
    db_session.commit()

    # Просроченная партия на дату 2026-09-10
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("4.000"),
        doc_number="DOC-EXP-1",
        batch_number="B-EXP-1",
        expiry_date=date(2026, 8, 25),
        unit_price=Decimal("500.00"),
    )
    # Годная партия
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 8, 1),
        quantity=Decimal("6.000"),
        doc_number="DOC-EXP-2",
        batch_number="B-EXP-2",
        expiry_date=date(2026, 12, 1),
        unit_price=Decimal("520.00"),
    )
    db_session.commit()

    resp = client.get("/api/stock?as_of=2026-09-10")
    assert resp.status_code == 200
    row = resp.json()["items"][0]
    assert row["current_stock"] == "10.000"
    assert row["available_stock"] == "6.000"
    assert row["expired_stock"] == "4.000"
    assert row["nearest_expiry_date"] == "2026-12-01"


def test_get_stock_by_sku_detail_and_unknown_sku(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка детализации по SKU, партиям, приходным документам и 404 для неизвестного SKU."""
    # Неизвестный SKU -> 404
    r_unk = client.get("/api/stock/UNKNOWN-SKU-999")
    assert r_unk.status_code == 404
    assert r_unk.json()["code"] == "NOT_FOUND"

    item = Item(sku="OIL-DET-01", name="Масло сандала", category="Масла", unit="л")
    loc1 = Location(code="LOC-DET-01", name="SPA Загород")
    loc2 = Location(code="LOC-DET-02", name="SPA Сити")
    db_session.add_all([item, loc1, loc2])
    db_session.commit()

    register_receipt(
        db_session,
        item=item,
        location=loc1,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("8.000"),
        doc_number="DOC-DET-REC1",
        batch_number="B-DET-1",
        expiry_date=date(2027, 5, 1),
        unit_price=Decimal("800.00"),
    )
    register_receipt(
        db_session,
        item=item,
        location=loc2,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("3.000"),
        doc_number="DOC-DET-REC2",
        batch_number="B-DET-2",
        expiry_date=date(2027, 6, 1),
        unit_price=Decimal("820.00"),
    )
    db_session.commit()

    # Детализация по SKU без указания location -> все объекты
    resp = client.get("/api/stock/OIL-DET-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sku"] == "OIL-DET-01"
    assert len(data["locations"]) == 2

    loc1_data = next(loc for loc in data["locations"] if loc["location"] == "LOC-DET-01")
    assert loc1_data["current_stock"] == "8.000"
    assert len(loc1_data["batches"]) == 1
    batch_detail = loc1_data["batches"][0]
    assert batch_detail["batch_number"] == "B-DET-1"
    assert batch_detail["receipt_doc_number"] == "DOC-DET-REC1"
    assert batch_detail["unit_price"] == "800.00"

    # Детализация с фильтром по location
    resp_filter = client.get("/api/stock/OIL-DET-01?location=LOC-DET-02")
    assert resp_filter.status_code == 200
    assert len(resp_filter.json()["locations"]) == 1
    assert resp_filter.json()["locations"][0]["location"] == "LOC-DET-02"

    # Запрос по неизвестному location -> 404
    r_unk_loc = client.get("/api/stock/OIL-DET-01?location=UNKNOWN-LOC")
    assert r_unk_loc.status_code == 404
    assert r_unk_loc.json()["code"] == "NOT_FOUND"
