"""Интеграционные тесты неизменности базы данных после расчёта плана закупок."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement, MovementAllocation, StockLock
from app.models.procurement import PurchaseOrder, SupplierCondition
from app.procurement_plan.repository import load_plan_database_snapshot
from tests.forecasting_fixtures import (
    make_purchase_order,
    make_receipt_record,
    make_supplier_condition,
)


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def _get_database_table_counts(session: Session) -> dict[str, int]:
    """Возвращает количество строк во всех предметных таблицах базы данных."""
    models = {
        "items": Item,
        "locations": Location,
        "suppliers": Supplier,
        "supplier_conditions": SupplierCondition,
        "purchase_orders": PurchaseOrder,
        "batches": Batch,
        "movements": Movement,
        "movement_allocations": MovementAllocation,
        "stock_locks": StockLock,
    }
    return {
        name: session.scalar(select(func.count()).select_from(m)) or 0 for name, m in models.items()
    }


def test_database_immutability_after_plan_request(
    client: TestClient,
    db_session: Session,
) -> None:
    """Проверка абсолютной неизменности БД после запроса плана закупок."""
    loc_msk = Location(code="LOC-MSK-IMM", name="Москва SPA")
    sup = Supplier(supplier_id="SUP-IMM", name="Поставщик Имм")
    it_oil = Item(sku="SKU-OIL-IMM", name="Масло Имм", category="Масла", unit="л")
    db_session.add_all([loc_msk, sup, it_oil])
    db_session.commit()

    make_supplier_condition(db_session, it_oil.id, sup.id)
    make_receipt_record(db_session, it_oil.id, loc_msk.id, date(2026, 9, 1), Decimal("100.00"))
    make_purchase_order(
        db_session,
        it_oil.id,
        loc_msk.id,
        sup.id,
        doc_number="PO-IMMUTABLE-01",
        expected_date=date(2026, 9, 30),
        expected_qty=Decimal("10.000"),
    )

    counts_before = _get_database_table_counts(db_session)

    # 1. Вызов репозитория напрямую
    snapshot = load_plan_database_snapshot(db_session, as_of=date(2026, 9, 15))
    assert len(snapshot.pairs) == 1
    assert len(snapshot.existing_orders) == 1

    counts_after_repo = _get_database_table_counts(db_session)
    assert counts_after_repo == counts_before

    # 2. Вызов через HTTP API POST /api/procurement/plan
    resp = client.post(
        "/api/procurement/plan",
        json={"as_of": "2026-09-15", "horizon_months": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["existing_orders"]) == 1
    assert data["existing_orders"][0]["doc_number"] == "PO-IMMUTABLE-01"

    counts_after_api = _get_database_table_counts(db_session)
    assert counts_after_api == counts_before
