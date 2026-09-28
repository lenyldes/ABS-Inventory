"""HTTP-проверка явного распределения количества при просмотре исправления расхода."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inventory.operations import register_consume, register_receipt
from app.main import app
from app.models.amendments import AmendmentSet
from app.models.catalog import Item, Location


def test_preview_rejects_allocation_sum_mismatch_without_saving_set(
    db_session: Session,
) -> None:
    """Несовпадение суммы строк расхода даёт 422 без сохранённого просмотра."""
    item = Item(sku="OIL-API-PREV-SUM", name="Масло для проверки", category="Масла", unit="л")
    loc = Location(code="LOC-API-PREV-SUM", name="SPA для проверки")
    db_session.add_all([item, loc])
    db_session.commit()

    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 10),
        quantity=Decimal("10.000"),
        doc_number="REC-PREV-SUM",
        batch_number="B-PREV-SUM",
        expiry_date=date(2027, 9, 10),
        unit_price=Decimal("100.00"),
    )
    consume = register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 15),
        quantity=Decimal("5.000"),
        doc_number="CONS-PREV-SUM",
    ).movement
    db_session.commit()
    allocation = consume.allocations[0]
    sets_before = db_session.execute(select(AmendmentSet.id)).scalars().all()

    response = TestClient(app).post(
        "/api/amendments/preview",
        json={
            "reason": "Проверка суммы строк",
            "operations": [
                {
                    "movement_id": consume.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {
                        "quantity": "4.000",
                        "allocation_quantities": [
                            {"allocation_id": allocation.id, "quantity": "3.000"}
                        ],
                    },
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ALLOCATION_SUM_MISMATCH"
    assert db_session.execute(select(AmendmentSet.id)).scalars().all() == sets_before
