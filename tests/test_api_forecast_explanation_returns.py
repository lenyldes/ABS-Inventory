"""HTTP-проверка происхождения возвратов в объяснении прогноза."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import register_consume, register_receipt, register_return
from app.main import app
from app.models.catalog import Item, Location, Supplier


def test_explanation_shows_linked_return_sources(
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Чистый расход раскрывает величину возврата и исходный документ списания."""
    item, location, _ = base_catalog
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 6, 1),
        quantity=Decimal("50.000"),
        doc_number="REC-RETURN",
        batch_number="B-RETURN",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    consume = register_consume(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 8, 15),
        quantity=Decimal("20.000"),
        doc_number="CON-RETURN",
    )
    returned = register_return(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 8, 20),
        quantity=Decimal("5.000"),
        doc_number="RET-RETURN",
        parent_movement_id=consume.movement.id,
        parent_allocation_id=consume.allocations[0].id,
    )
    db_session.commit()

    response = TestClient(app).post(
        "/api/forecast",
        json={
            "sku": item.sku,
            "location": location.code,
            "as_of": "2026-09-01",
            "horizon_days": 30,
        },
    )
    assert response.status_code == 200
    explanation = response.json()["explanation"]
    data_used = {entry["name"]: entry for entry in explanation["data_used"]}

    assert data_used["gross_consumption_90d"]["value"] == "20.000"
    assert data_used["linked_returns_90d"]["value"] == "5.000"
    assert data_used["total_consumption_90d"]["value"] == "15.000"
    return_source = data_used[f"linked_return_{returned.movement.id}"]
    assert return_source["value"] == "5.000"
    assert "RET-RETURN" in return_source["source"]
    assert "CON-RETURN" in return_source["source"]
    assert any("связанные возвраты" in formula for formula in explanation["formulas"])
