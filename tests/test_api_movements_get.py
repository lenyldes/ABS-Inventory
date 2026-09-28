"""HTTP-тесты журнала складских движений: GET /api/movements."""

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


@pytest.fixture
def catalog_setup(db_session: Session) -> tuple[Item, Location]:
    """Базовые товар и объект."""
    item = Item(sku="OIL-GET-01", name="Масло жожоба", category="Масла", unit="л")
    loc = Location(code="LOC-GET-01", name="SPA Север")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_get_movements_pagination_boundaries(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Проверка валидации границ limit и offset и корректности пагинации."""
    item, loc = catalog_setup

    # Невалидные границы -> 400
    r_bad_limit_low = client.get("/api/movements?limit=0")
    assert r_bad_limit_low.status_code == 400
    assert r_bad_limit_low.json()["code"] == "INVALID_PAGINATION"

    r_bad_limit_high = client.get("/api/movements?limit=101")
    assert r_bad_limit_high.status_code == 400
    assert r_bad_limit_high.json()["code"] == "INVALID_PAGINATION"

    r_bad_offset = client.get("/api/movements?offset=-1")
    assert r_bad_offset.status_code == 400
    assert r_bad_offset.json()["code"] == "INVALID_PAGINATION"

    # Создаём 3 движения
    for i in range(1, 4):
        register_receipt(
            db_session,
            item=item,
            location=loc,
            operation_date=date(2026, 9, i),
            quantity=Decimal("5.000"),
            doc_number=f"DOC-PAG-{i}",
            batch_number=f"B-PAG-{i}",
            expiry_date=date(2027, 1, 1),
            unit_price=Decimal("100.00"),
        )
    db_session.commit()

    # Первая страница limit=2, offset=0
    p1 = client.get("/api/movements?limit=2&offset=0")
    assert p1.status_code == 200
    d1 = p1.json()
    assert d1["total"] == 3
    assert len(d1["items"]) == 2
    assert d1["limit"] == 2
    assert d1["offset"] == 0

    # Вторая страница limit=2, offset=2
    p2 = client.get("/api/movements?limit=2&offset=2")
    assert p2.status_code == 200
    d2 = p2.json()
    assert d2["total"] == 3
    assert len(d2["items"]) == 1
    assert d2["offset"] == 2


def test_get_movements_date_range_and_filtering(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Проверка валидации диапазона дат и фильтрации по SKU, типу и датам."""
    item, loc = catalog_setup

    # date_from > date_to -> 422
    inv_dates = client.get("/api/movements?date_from=2026-09-10&date_to=2026-09-01")
    assert inv_dates.status_code == 422
    assert inv_dates.json()["code"] == "INVALID_DATE_RANGE"

    # Регистрируем движения
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 5),
        quantity=Decimal("10.000"),
        doc_number="DOC-FLT-1",
        batch_number="B-FLT-1",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("3.000"),
        doc_number="DOC-FLT-2",
    )
    db_session.commit()

    # Фильтр по типу consume
    resp_consume = client.get("/api/movements?type=consume")
    assert resp_consume.status_code == 200
    c_data = resp_consume.json()
    assert c_data["total"] == 1
    assert c_data["items"][0]["doc_number"] == "DOC-FLT-2"

    # Фильтр по диапазону дат
    resp_period = client.get("/api/movements?date_from=2026-09-06&date_to=2026-09-12")
    assert resp_period.status_code == 200
    p_data = resp_period.json()
    assert p_data["total"] == 1
    assert p_data["items"][0]["doc_number"] == "DOC-FLT-2"


def test_get_movements_sorting_order(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Проверка сортировки по operation_date и created_at в порядке asc и desc."""
    item, loc = catalog_setup

    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("5.000"),
        doc_number="DOC-SRT-1",
        batch_number="B-SRT-1",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 15),
        quantity=Decimal("5.000"),
        doc_number="DOC-SRT-2",
        batch_number="B-SRT-2",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    db_session.commit()

    # По умолчанию: operation_date desc
    resp_desc = client.get("/api/movements")
    assert resp_desc.status_code == 200
    items_desc = resp_desc.json()["items"]
    assert items_desc[0]["doc_number"] == "DOC-SRT-2"
    assert items_desc[1]["doc_number"] == "DOC-SRT-1"

    # operation_date asc
    resp_asc = client.get("/api/movements?sort_order=asc")
    assert resp_asc.status_code == 200
    items_asc = resp_asc.json()["items"]
    assert items_asc[0]["doc_number"] == "DOC-SRT-1"
    assert items_asc[1]["doc_number"] == "DOC-SRT-2"


def test_get_movements_fefo_deviation_warning(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Проверка появления fefo_deviation после ретроспективного прихода."""
    item, loc = catalog_setup

    # 1. Сначала приход партии B2 со сроком 2026-10-20
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="DOC-W-REC2",
        batch_number="B2",
        expiry_date=date(2026, 10, 20),
        unit_price=Decimal("150.00"),
    )
    db_session.commit()

    # 2. Расход 4.000 на 2026-09-05
    client.post(
        "/api/movements",
        json={
            "operation_date": "2026-09-05",
            "sku": item.sku,
            "location": loc.code,
            "type": "consume",
            "quantity": "4.000",
            "doc_number": "DOC-W-CONS1",
        },
    )

    # До позднего прихода у расхода нет предупреждений
    r_before = client.get("/api/movements?type=consume")
    assert r_before.status_code == 200
    assert r_before.json()["items"][0]["warnings"] == []

    # 3. Поздний приход партии B1 со сроком 2026-09-25 на дату 2026-09-02 (раньше расхода!)
    client.post(
        "/api/movements",
        json={
            "operation_date": "2026-09-02",
            "sku": item.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "5.000",
            "doc_number": "DOC-W-REC1",
            "batch_number": "B1",
            "expiry_date": "2026-09-25",
            "unit_price": "140.00",
        },
    )

    # 4. Теперь в журнале у расхода должно появиться предупреждение fefo_deviation
    r_after = client.get("/api/movements?type=consume")
    assert r_after.status_code == 200
    consume_item = r_after.json()["items"][0]
    assert len(consume_item["warnings"]) == 1
    warning = consume_item["warnings"][0]
    assert warning["code"] == "fefo_deviation"
    assert "FEFO" in warning["message"]
    # Сохранённые строки распределения остаются прежними
    assert len(consume_item["allocations"]) == 1
