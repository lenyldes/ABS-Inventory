"""Тесты замечаний аудита:
- уникальность doc_number по объекту;
- отрицательная корректировка quantity;
- связь версии возврата с набором исправлений.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import (
    register_correction,
    register_receipt,
)
from app.main import app
from app.models.catalog import Item, Location
from app.models.inventory import Movement


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


def test_preview_duplicate_doc_number_across_different_items_on_same_location(
    client: TestClient,
    db_session: Session,
) -> None:
    """Preview отклоняет дубликат doc_number, занятый движением другого товара на объекте."""
    item1 = Item(sku="ITEM-DUP-01", name="Товар 1", category="Кат", unit="л")
    item2 = Item(sku="ITEM-DUP-02", name="Товар 2", category="Кат", unit="л")
    loc = Location(code="LOC-DUP-01", name="Объект 1")
    db_session.add_all([item1, item2, loc])
    db_session.commit()

    rec2 = register_receipt(
        db_session,
        item=item2,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="DOC-TAKEN-BY-ITEM2",
        batch_number="B-ITEM2",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    rec1 = register_receipt(
        db_session,
        item=item1,
        location=loc,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("10.000"),
        doc_number="DOC-ORIG-ITEM1",
        batch_number="B-ITEM1",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("150.00"),
    )
    db_session.commit()

    # Пытаемся изменить номер документа движения товара 1 на номер, занятый товаром 2
    resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Попытка использовать занятый номер",
            "operations": [
                {
                    "movement_id": rec1.movement.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"doc_number": "DOC-TAKEN-BY-ITEM2"},
                }
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["can_apply"] is False
    assert len(data["blockers"]) >= 1
    dup_blocker = next(b for b in data["blockers"] if b["code"] == "DUPLICATE_DOC_NUMBER")
    assert dup_blocker["details"]["doc_number"] == "DOC-TAKEN-BY-ITEM2"
    assert dup_blocker["details"]["conflicting_movement_id"] == rec2.movement.id


def test_correction_negative_quantity_preview_and_confirm(
    client: TestClient,
    db_session: Session,
) -> None:
    """Парсер и confirm разрешают отрицательное количество для инвентаризационной корректировки."""
    item = Item(sku="ITEM-CORR-01", name="Товар Корр", category="Кат", unit="л")
    loc = Location(code="LOC-CORR-01", name="Объект Корр")
    db_session.add_all([item, loc])
    db_session.commit()

    rec = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("20.000"),
        doc_number="REC-CORR-01",
        batch_number="B-CORR-01",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    corr = register_correction(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("5.000"),
        doc_number="CORR-01",
        batch_id=rec.movement.batch_id,
        reason="Первичный излишек",
    )
    db_session.commit()

    # Меняем количество корректировки на отрицательное (-3.000)
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Фактическая недостача при инвентаризации",
            "operations": [
                {
                    "movement_id": corr.movement.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "-3.000"},
                }
            ],
        },
    )
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert prev_data["can_apply"] is True

    # Подтверждаем
    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_data["preview_id"],
            "version_signature": prev_data["version_signature"],
            "reason": "Фактическая недостача при инвентаризации",
        },
    )
    assert conf_resp.status_code == 200

    db_session.expire_all()
    db_corr = db_session.get(Movement, corr.movement.id)
    assert db_corr is not None
    assert db_corr.quantity == Decimal("-3.000")
    assert db_corr.current_version == 2


def test_correction_zero_quantity_rejected_by_parser(
    client: TestClient,
    db_session: Session,
) -> None:
    """Парсер категорически отклоняет нулевое количество для корректировки."""
    item = Item(sku="ITEM-CORR-02", name="Товар Корр 2", category="Кат", unit="л")
    loc = Location(code="LOC-CORR-02", name="Объект Корр 2")
    db_session.add_all([item, loc])
    db_session.commit()

    rec = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("20.000"),
        doc_number="REC-CORR-02",
        batch_number="B-CORR-02",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    corr = register_correction(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("2.000"),
        doc_number="CORR-02",
        batch_id=rec.movement.batch_id,
        reason="Излишек",
    )
    db_session.commit()

    resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Попытка обнулить корректировку",
            "operations": [
                {
                    "movement_id": corr.movement.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "0.000"},
                }
            ],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "ZERO_QUANTITY"


def test_receipt_negative_quantity_rejected_by_parser(
    client: TestClient,
    db_session: Session,
) -> None:
    """Парсер отклоняет отрицательное количество для прихода."""
    item = Item(sku="ITEM-REC-NEG", name="Товар Приход", category="Кат", unit="л")
    loc = Location(code="LOC-REC-NEG", name="Объект Приход")
    db_session.add_all([item, loc])
    db_session.commit()

    rec = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-NEG-01",
        batch_number="B-REC-NEG-01",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    db_session.commit()

    resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Отрицательный приход",
            "operations": [
                {
                    "movement_id": rec.movement.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "-5.000"},
                }
            ],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_QUANTITY"
