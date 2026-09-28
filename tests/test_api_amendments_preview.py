"""HTTP-тесты для задачи 3.2: предварительный просмотр наборов исправлений.

POST /api/amendments/preview.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inventory.operations import register_consume, register_receipt
from app.main import app
from app.models.amendments import AmendmentEntry, AmendmentSet
from app.models.catalog import Item, Location
from app.models.inventory import Batch, Movement


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


@pytest.fixture
def catalog_setup(db_session: Session) -> tuple[Item, Location]:
    """Базовые товар и объект для тестирования preview."""
    item = Item(sku="OIL-API-PREV-01", name="Масло бергамота", category="Масла", unit="л")
    loc = Location(code="LOC-API-PREV-01", name="SPA Восток")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_preview_success_and_no_stock_changes(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Успешный просмотр сохраняет набор, возвращает дельту остатка и не меняет склад."""
    item, loc = catalog_setup

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("20.000"),
        doc_number="REC-PREV-01",
        batch_number="B-PREV-01",
        expiry_date=date(2027, 9, 10),
        unit_price=Decimal("200.00"),
    )
    cons_res = register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 15),
        quantity=Decimal("10.000"),
        doc_number="CONS-PREV-01",
    )
    db_session.commit()
    rec = rec_res.movement
    cons = cons_res.movement

    # Запрос предварительного просмотра: уменьшить приход до 15.000
    resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Уточнение партии по ТТН",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "15.000"},
                }
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["can_apply"] is True
    assert data["version_signature"].startswith("sig_")
    assert len(data["preview_id"]) > 10
    assert data["blockers"] == []
    assert data["affected_operations"] == [rec.id]

    assert len(data["stock_impact"]) == 1
    impact = data["stock_impact"][0]
    assert impact["sku"] == item.sku
    assert impact["location"] == loc.code
    assert impact["current_stock_before"] == "10.000"
    assert impact["current_stock_after"] == "5.000"

    # Проверяем сохранение набора и операций в БД
    saved_set = db_session.execute(
        select(AmendmentSet).where(AmendmentSet.amendment_id == data["preview_id"])
    ).scalar_one_or_none()
    assert saved_set is not None
    assert saved_set.status == "preview"
    assert saved_set.reason == "Уточнение партии по ТТН"

    entries = list(
        db_session.execute(
            select(AmendmentEntry).where(AmendmentEntry.amendment_set_id == saved_set.id)
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].movement_id == rec.id
    assert entries[0].action == "update"

    # Проверяем, что склад в БД не изменился
    db_rec = db_session.get(Movement, rec.id)
    assert db_rec is not None
    assert db_rec.quantity == Decimal("20.000")

    db_cons = db_session.get(Movement, cons.id)
    assert db_cons is not None
    assert db_cons.quantity == Decimal("10.000")

    db_batch = db_session.get(Batch, rec.batch_id)
    assert db_batch is not None
    assert db_batch.receipt_doc_number == "REC-PREV-01"


def test_preview_with_blocker_returns_200_can_apply_false(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Предварительный просмотр с дефицитом возвращает 200 OK с can_apply: false и блокером."""
    item, loc = catalog_setup

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("10.000"),
        doc_number="REC-PREV-02",
        batch_number="B-PREV-02",
        expiry_date=date(2027, 9, 10),
        unit_price=Decimal("100.00"),
    )
    register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 15),
        quantity=Decimal("10.000"),
        doc_number="CONS-PREV-02",
    )
    db_session.commit()
    rec = rec_res.movement

    # Попытка уменьшить приход до 5.000 при расходе 10.000 создаёт дефицит
    resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Ошибка оператора",
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
    assert resp.status_code == 200
    data = resp.json()
    assert data["can_apply"] is False
    assert len(data["blockers"]) == 1
    assert data["blockers"][0]["code"] == "HISTORICAL_DEFICIT"
    assert data["blockers"][0]["deficit_qty"] == "5.000"


def test_preview_400_empty_reason_or_operations(client: TestClient) -> None:
    """Отказ 400 при пустой причине или пустом списке операций."""
    # Нет причины
    resp_no_reason = client.post(
        "/api/amendments/preview",
        json={
            "reason": "   ",
            "operations": [{"movement_id": 1, "action": "cancel", "expected_version": 1}],
        },
    )
    assert resp_no_reason.status_code == 400
    assert resp_no_reason.json()["code"] == "EMPTY_REASON"

    # Пустой список операций
    resp_no_ops = client.post(
        "/api/amendments/preview",
        json={"reason": "Тест", "operations": []},
    )
    assert resp_no_ops.status_code == 400
    assert resp_no_ops.json()["code"] == "EMPTY_OPERATIONS"


def test_preview_404_movement_not_found(client: TestClient) -> None:
    """Отказ 404 при отсутствии движения с указанным movement_id."""
    resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Тест",
            "operations": [{"movement_id": 999999, "action": "cancel", "expected_version": 1}],
        },
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_preview_422_sku_change_or_invalid_fields(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Отказ 422 при попытке смены SKU или некорректных полях."""
    item, loc = catalog_setup
    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("10.000"),
        doc_number="REC-PREV-03",
        batch_number="B-PREV-03",
        expiry_date=date(2027, 9, 10),
        unit_price=Decimal("100.00"),
    )
    db_session.commit()
    rec = rec_res.movement

    # Попытка смены SKU
    resp_sku = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Тест",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"sku": "NEW-SKU-FORBIDDEN"},
                }
            ],
        },
    )
    assert resp_sku.status_code == 422
    assert resp_sku.json()["code"] == "SKU_IMMUTABLE"

    # Недопустимое поле
    resp_extra = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Тест",
            "operations": [
                {
                    "movement_id": rec.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"unknown_extra_field": 123},
                }
            ],
        },
    )
    assert resp_extra.status_code == 422
    assert resp_extra.json()["code"] == "INVALID_FIELD"


def test_preview_422_missing_expected_version_creates_no_set(
    client: TestClient,
    db_session: Session,
) -> None:
    """Отсутствующая версия отклоняется до создания набора исправлений."""
    response = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Проверка обязательной версии",
            "operations": [{"movement_id": 1, "action": "cancel"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert any(
        error.startswith("body.operations.0.expected_version:")
        for error in response.json()["details"]["errors"]
    )
    assert db_session.execute(select(AmendmentSet)).scalars().first() is None
