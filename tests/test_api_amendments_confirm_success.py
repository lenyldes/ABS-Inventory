"""HTTP-тесты успешного подтверждения наборов складских исправлений.

Проверяет POST /api/amendments/confirm.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inventory.operations import register_consume, register_receipt
from app.main import app
from app.models.amendments import AmendmentSet, MovementVersion
from app.models.catalog import Item, Location
from app.models.inventory import Movement


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


@pytest.fixture
def catalog_setup(db_session: Session) -> tuple[Item, Location]:
    """Базовые товар и объект для тестирования confirm."""
    item = Item(sku="OIL-CONF-01", name="Масло сандала", category="Масла", unit="л")
    loc = Location(code="LOC-CONF-01", name="SPA Запад")
    db_session.add_all([item, loc])
    db_session.commit()
    return item, loc


def test_confirm_success_and_audit_version_created(
    client: TestClient,
    db_session: Session,
    catalog_setup: tuple[Item, Location],
) -> None:
    """Успешное подтверждение применяет правку, инкрементирует версию и пишет аудит."""
    item, loc = catalog_setup

    rec_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("20.000"),
        doc_number="REC-CONF-01",
        batch_number="B-CONF-01",
        expiry_date=date(2027, 9, 10),
        unit_price=Decimal("200.00"),
    )
    register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 15),
        quantity=Decimal("10.000"),
        doc_number="CONS-CONF-01",
    )
    db_session.commit()
    rec = rec_res.movement

    # 1. Preview: уменьшить приход до 15.000
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Уточнение накладной",
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
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert prev_data["can_apply"] is True

    # 2. Confirm
    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_data["preview_id"],
            "version_signature": prev_data["version_signature"],
            "reason": "Уточнение накладной",
        },
    )
    assert conf_resp.status_code == 200
    conf_data = conf_resp.json()
    assert conf_data["status"] == "applied"
    assert conf_data["amendment_id"] == prev_data["preview_id"]
    assert len(conf_data["applied_movements"]) == 1
    assert conf_data["applied_movements"][0]["movement_id"] == rec.id
    assert conf_data["applied_movements"][0]["version"] == 2
    assert conf_data["applied_movements"][0]["action"] == "update"

    # Проверяем базу данных
    db_session.expire_all()
    db_rec = db_session.get(Movement, rec.id)
    assert db_rec is not None
    assert db_rec.quantity == Decimal("15.000")
    assert db_rec.current_version == 2

    # Проверяем аудит версий
    versions = list(
        db_session.execute(
            select(MovementVersion)
            .where(MovementVersion.movement_id == rec.id)
            .order_by(MovementVersion.version_num.asc())
        )
        .scalars()
        .all()
    )
    assert len(versions) == 2
    assert versions[0].version_num == 1
    assert versions[1].version_num == 2
    assert versions[1].action == "update"
    assert versions[1].reason == "Уточнение накладной"
    assert versions[1].snapshot["quantity"] == "15.000"

    # Проверяем статус amendment_set
    saved_set = db_session.execute(
        select(AmendmentSet).where(AmendmentSet.amendment_id == prev_data["preview_id"])
    ).scalar_one()
    assert saved_set.status == "applied"
    assert saved_set.applied_at is not None
