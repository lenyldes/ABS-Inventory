"""HTTP-тесты обработки ошибок при регистрации движений: POST /api/movements."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.catalog import Item, Location


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


@pytest.fixture
def base_catalog(db_session: Session) -> tuple[Item, Location]:
    """Базовые товар и объект для тестов."""
    item = Item(sku="OIL-ERR-01", name="Масло розмарина", category="Масла", unit="л")
    loc = Location(code="LOC-ERR", name="Склад ошибок")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_post_movement_unknown_references(
    client: TestClient,
    base_catalog: tuple[Item, Location],
) -> None:
    """Проверка возврата кода 404 и структуры ошибки при неизвестных ссылках."""
    item, loc = base_catalog

    # Неизвестный SKU
    r1 = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": "NON-EXISTENT-SKU",
            "location": loc.code,
            "type": "receipt",
            "quantity": "5.000",
            "doc_number": "DOC-UNK-1",
            "batch_number": "B-UNK-1",
            "unit_price": "100.00",
        },
    )
    assert r1.status_code == 404
    assert r1.json()["code"] == "NOT_FOUND"

    # Неизвестный Location
    r2 = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": "LOC-NON-EXISTENT",
            "type": "receipt",
            "quantity": "5.000",
            "doc_number": "DOC-UNK-2",
            "batch_number": "B-UNK-2",
            "unit_price": "100.00",
        },
    )
    assert r2.status_code == 404
    assert r2.json()["code"] == "NOT_FOUND"

    # Неизвестный batch_id при списании
    r3 = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "writeoff",
            "quantity": "1.000",
            "doc_number": "DOC-UNK-3",
            "batch_id": 99999,
            "reason": "Тест",
        },
    )
    assert r3.status_code == 404
    assert r3.json()["code"] == "NOT_FOUND"

    # Неизвестный поставщик при receipt
    r4 = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "5.000",
            "doc_number": "DOC-UNK-4",
            "batch_number": "B-UNK-4",
            "unit_price": "100.00",
            "supplier_id": "SUP-UNKNOWN",
        },
    )
    assert r4.status_code == 404
    assert r4.json()["code"] == "NOT_FOUND"


def test_post_movement_malformed_json(client: TestClient) -> None:
    """Проверка возврата кода 400 при невалидном синтаксисе JSON."""
    response = client.post(
        "/api/movements",
        content=b'{"operation_date": "2026-09-28", "sku": broken json',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "INVALID_JSON"
    assert "невалидный JSON" in data["message"]


def test_post_movement_future_date_rejected(
    client: TestClient,
    base_catalog: tuple[Item, Location],
) -> None:
    """Проверка возврата кода 422 при указании будущей даты операции."""
    item, loc = base_catalog
    future_date = date.today() + timedelta(days=1)

    response = client.post(
        "/api/movements",
        json={
            "operation_date": future_date.isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "5.000",
            "doc_number": "DOC-FUT-01",
            "batch_number": "B-FUT-01",
            "unit_price": "100.00",
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "FUTURE_DATE"


def test_post_movement_invalid_quantities(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location],
) -> None:
    """Проверка возврата кода 422 при неположительном количестве и неделимости штук."""
    item, loc = base_catalog

    # Количество <= 0 для поступления
    r1 = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "-5.000",
            "doc_number": "DOC-QTY-1",
            "batch_number": "B-QTY-1",
            "unit_price": "100.00",
        },
    )
    assert r1.status_code == 422

    # Количество 0 для корректировки
    r2 = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "correction",
            "quantity": "0.000",
            "doc_number": "DOC-QTY-2",
            "batch_id": 1,
            "reason": "Нулевая разница",
        },
    )
    assert r2.status_code == 422

    # Дробное количество для товара в штуках
    item_pcs = Item(sku="TOWEL-01", name="Полотенце", category="Текстиль", unit="шт")
    db_session.add(item_pcs)
    db_session.commit()

    r3 = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item_pcs.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "2.500",
            "doc_number": "DOC-PCS-1",
            "batch_number": "B-PCS-1",
            "unit_price": "200.00",
        },
    )
    assert r3.status_code == 422
    assert r3.json()["code"] == "FRACTIONAL_PIECES"


def test_post_movement_insufficient_stock_and_duplicate_doc(
    client: TestClient,
    base_catalog: tuple[Item, Location],
) -> None:
    """Проверка возврата 422 при нехватке остатка и 409 при повторе номера документа."""
    item, loc = base_catalog

    # Поступление 5.000
    rec_res = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "5.000",
            "doc_number": "DOC-DUP-01",
            "batch_number": "B-DUP-01",
            "unit_price": "100.00",
        },
    )
    assert rec_res.status_code == 201

    # Повтор того же doc_number на том же объекте -> 409
    dup_res = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "receipt",
            "quantity": "1.000",
            "doc_number": "DOC-DUP-01",
            "batch_number": "B-DUP-02",
            "unit_price": "100.00",
        },
    )
    assert dup_res.status_code == 409
    assert dup_res.json()["code"] == "DOCUMENT_DUPLICATE"

    # Расход больше доступного остатка (10 > 5) -> 422
    insuf_res = client.post(
        "/api/movements",
        json={
            "operation_date": date.today().isoformat(),
            "sku": item.sku,
            "location": loc.code,
            "type": "consume",
            "quantity": "10.000",
            "doc_number": "DOC-INSUF-01",
        },
    )
    assert insuf_res.status_code == 422
    assert insuf_res.json()["code"] == "INSUFFICIENT_STOCK"
