"""Интеграционные тесты для задачи 4.3: аудит смены партии с зависимым возвратом."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.inventory.operations import register_consume, register_receipt, register_return
from app.main import app
from app.models.catalog import Item, Location
from app.models.inventory import Movement


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


def test_batch_swap_with_dependent_return_history_integrity(
    client: TestClient,
    db_session: Session,
) -> None:
    """Смена партии расхода обновляет связанный возврат и фиксирует аудит обоих движений."""
    item = Item(sku="OIL-SWAP-01", name="Масло эвкалипта", category="Масла", unit="л")
    loc = Location(code="LOC-SWAP-01", name="SPA Главный")
    db_session.add_all([item, loc])
    db_session.commit()

    # Две партии: B1 (100 руб) и B2 (200 руб)
    rec1_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-SWAP-B1",
        batch_number="B1",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
    )
    rec2_res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 2),
        quantity=Decimal("10.000"),
        doc_number="REC-SWAP-B2",
        batch_number="B2",
        expiry_date=date(2027, 2, 1),
        unit_price=Decimal("200.00"),
    )
    db_session.commit()
    rec1 = rec1_res.movement
    rec2 = rec2_res.movement

    # Расход 5 л из партии B1
    cons_res = register_consume(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 5),
        quantity=Decimal("5.000"),
        doc_number="CONS-SWAP-01",
    )
    db_session.commit()
    cons = cons_res.movement
    cons_alloc = cons.allocations[0]
    assert cons_alloc.batch_id == rec1.batch_id

    # Возврат 2 л по строке расхода
    ret_res = register_return(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 6),
        quantity=Decimal("2.000"),
        doc_number="RET-SWAP-01",
        parent_movement_id=cons.id,
        parent_allocation_id=cons_alloc.id,
    )
    db_session.commit()
    ret = ret_res.movement
    assert ret.batch_id == rec1.batch_id

    # Preview: меняем партию в строке расхода с B1 на B2
    prev_resp = client.post(
        "/api/amendments/preview",
        json={
            "reason": "Фактически выдана партия B2 вместо B1",
            "operations": [
                {
                    "movement_id": cons.id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {
                        "allocation_id": cons_alloc.id,
                        "batch_id": rec2.batch_id,
                    },
                }
            ],
        },
    ).json()

    assert prev_resp["can_apply"] is True
    assert set(prev_resp["affected_operations"]) == {cons.id, ret.id}

    # Confirm
    conf_resp = client.post(
        "/api/amendments/confirm",
        json={
            "preview_id": prev_resp["preview_id"],
            "version_signature": prev_resp["version_signature"],
            "reason": "Фактически выдана партия B2 вместо B1",
        },
    )
    assert conf_resp.status_code == 200

    # Проверяем, что и расход, и возврат перешли на новую партию B2
    db_session.expire_all()
    db_cons = db_session.get(Movement, cons.id)
    assert db_cons is not None
    assert db_cons.allocations[0].batch_id == rec2.batch_id
    assert db_cons.allocations[0].unit_price == Decimal("200.00")
    assert db_cons.current_version == 2

    db_ret = db_session.get(Movement, ret.id)
    assert db_ret is not None
    assert db_ret.batch_id == rec2.batch_id
    assert db_ret.current_version == 2

    # Проверяем версионирование и историю
    ret_hist_resp = client.get(f"/api/movements/{ret.id}/history")
    assert ret_hist_resp.status_code == 200
    ret_hist = ret_hist_resp.json()
    assert len(ret_hist["versions"]) == 2
    assert ret_hist["versions"][1]["action"] == "update"
    assert ret_hist["versions"][1]["reason"] == "Фактически выдана партия B2 вместо B1"
    assert ret_hist["versions"][1]["snapshot"]["amendment_id"] == prev_resp["preview_id"]

    cons_hist_resp = client.get(f"/api/movements/{cons.id}/history")
    assert cons_hist_resp.status_code == 200
    cons_hist = cons_hist_resp.json()
    assert cons_hist["versions"][1]["snapshot"]["amendment_id"] == prev_resp["preview_id"]
