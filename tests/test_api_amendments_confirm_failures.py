"""HTTP-тесты отказов при подтверждении исправлений (POST /api/amendments/confirm)."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import register_consume, register_receipt
from app.main import app
from app.models.catalog import Item, Location
from app.models.inventory import Movement


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


@pytest.fixture
def catalog_setup(db_session: Session) -> tuple[Item, Location]:
    """Базовые товар и объект для тестирования confirm."""
    item = Item(sku="OIL-CONF-02", name="Масло сандала", category="Масла", unit="л")
    loc = Location(code="LOC-CONF-02", name="SPA Запад")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_confirm_409_stale_preview(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Отказ 409 Conflict при попытке подтверждения устаревшего предварительного просмотра."""
    item, loc = catalog_setup

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("20.000"),
        doc_number="REC-CONF-02",
        batch_number="B-CONF-02",
        expiry_date=date(2027, 9, 10),
        unit_price=Decimal("200.00"),
    )
    db_session.commit()
    rec = rec_res.movement

    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Тест устаревания",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "18.000"},
                }
            ],
        },
    )
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()

    # Между preview и confirm проводим новое движение расхода
    register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 12),
        quantity=Decimal("2.000"),
        doc_number="CONS-INTERMEDIATE",
    )
    db_session.commit()

    # Попытка подтвердить preview завершается отказом 409 stale_preview
    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_data["preview_id"],
            "version_signature": prev_data["version_signature"],
            "reason": "Тест устаревания",
        },
    )
    assert conf_resp.status_code == 409
    assert conf_resp.json()["code"] == "stale_preview"

    # Движение не изменилось
    db_rec = db_session.get(Movement, rec.id)
    assert db_rec is not None
    assert db_rec.quantity == Decimal("20.000")
    assert db_rec.current_version == 1


def test_confirm_409_repeat_confirmation(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Повторное подтверждение уже применённого набора отклоняется с 409 Conflict."""
    item, loc = catalog_setup

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("20.000"),
        doc_number="REC-CONF-03",
        batch_number="B-CONF-03",
        expiry_date=date(2027, 9, 10),
        unit_price=Decimal("200.00"),
    )
    db_session.commit()
    rec = rec_res.movement

    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Тест повтора",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "16.000"},
                }
            ],
        },
    )
    prev_data = prev_resp.json()

    # Первое подтверждение успешно
    resp1 = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_data["preview_id"],
            "version_signature": prev_data["version_signature"],
            "reason": "Тест повтора",
        },
    )
    assert resp1.status_code == 200

    # Второе подтверждение отклоняется
    resp2 = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_data["preview_id"],
            "version_signature": prev_data["version_signature"],
            "reason": "Тест повтора",
        },
    )
    assert resp2.status_code == 409
    assert resp2.json()["code"] == "stale_preview"


def test_confirm_rollback_on_dependency_violation(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Откат всего набора и 422 dependency_violation при появлении нарушения зависимостей."""
    item, loc = catalog_setup

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("10.000"),
        doc_number="REC-CONF-04",
        batch_number="B-CONF-04",
        expiry_date=date(2027, 9, 10),
        unit_price=Decimal("100.00"),
    )
    register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 15),
        quantity=Decimal("10.000"),
        doc_number="CONS-CONF-04",
    )
    db_session.commit()
    rec = rec_res.movement

    # Создаём preview, который изначально нарушает баланс (can_apply: false)
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Попытка дефицита",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "5.000"},
                }
            ],
        },
    )
    prev_data = prev_resp.json()
    assert prev_data["can_apply"] is False

    # Попытка подтвердить preview с блокером возвращает 422 dependency_violation
    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_data["preview_id"],
            "version_signature": prev_data["version_signature"],
            "reason": "Попытка дефицита",
        },
    )
    assert conf_resp.status_code == 422
    assert conf_resp.json()["code"] == "dependency_violation"

    # Приход остался неизменным
    db_rec = db_session.get(Movement, rec.id)
    assert db_rec is not None
    assert db_rec.quantity == Decimal("10.000")
    assert db_rec.current_version == 1
