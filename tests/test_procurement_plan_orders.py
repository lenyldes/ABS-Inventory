"""Интеграционные тесты действующих заказов и исключения двойного учёта в плане."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.catalog import Item, Location, Supplier
from app.procurement_plan.repository import load_plan_database_snapshot
from tests.forecasting_fixtures import make_purchase_order


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


@pytest.fixture
def catalog_setup(db_session: Session) -> dict[str, list]:
    """Тестовые справочники для проверки действующих заказов."""
    loc_msk = Location(code="LOC-MSK", name="Москва SPA")
    loc_spb = Location(code="LOC-SPB", name="СПб SPA")
    db_session.add_all([loc_msk, loc_spb])

    sup1 = Supplier(supplier_id="SUP-01", name="Поставщик 1")
    sup2 = Supplier(supplier_id="SUP-02", name="Поставщик 2")
    db_session.add_all([sup1, sup2])

    it_oil1 = Item(sku="SKU-OIL-1", name="Масло Арганы", category="Масла", unit="л")
    it_crm1 = Item(sku="SKU-CRM-1", name="Крем для лица", category="Кремы", unit="шт")
    db_session.add_all([it_oil1, it_crm1])
    db_session.commit()

    return {
        "locations": [loc_msk, loc_spb],
        "suppliers": [sup1, sup2],
        "items": [it_oil1, it_crm1],
    }


def test_load_snapshot_no_double_counting_of_existing_orders(
    db_session: Session,
    catalog_setup: dict[str, list],
) -> None:
    """Проверка отсутствия двойного учёта: учёт только pending_qty, исключение отмен и 0."""
    it_oil1 = catalog_setup["items"][0]
    loc_msk = catalog_setup["locations"][0]
    loc_spb = catalog_setup["locations"][1]
    sup1 = catalog_setup["suppliers"][0]
    as_of = date(2026, 9, 20)

    # 1. Действующий будущий заказ
    make_purchase_order(
        db_session,
        it_oil1.id,
        loc_msk.id,
        sup1.id,
        doc_number="PO-ACT-01",
        expected_date=date(2026, 9, 25),
        expected_qty=Decimal("15.000"),
        unit_price=Decimal("140.00"),
    )

    # 2. Задержанный заказ (expected_date <= as_of)
    make_purchase_order(
        db_session,
        it_oil1.id,
        loc_msk.id,
        sup1.id,
        doc_number="PO-DEL-01",
        expected_date=date(2026, 9, 18),
        expected_qty=Decimal("5.000"),
        unit_price=Decimal("140.00"),
    )

    # 3. Частично полученный заказ (из 20 получено 12, в пути ровно 8)
    make_purchase_order(
        db_session,
        it_oil1.id,
        loc_msk.id,
        sup1.id,
        doc_number="PO-PART-01",
        expected_date=date(2026, 9, 28),
        expected_qty=Decimal("20.000"),
        received_qty=Decimal("12.000"),
        pending_qty=Decimal("8.000"),
        status="partially_received",
        unit_price=Decimal("142.00"),
    )

    # 4. Полностью полученный заказ (pending_qty = 0) — должен быть ИСКЛЮЧЁН
    make_purchase_order(
        db_session,
        it_oil1.id,
        loc_msk.id,
        sup1.id,
        doc_number="PO-REC-01",
        expected_date=date(2026, 9, 10),
        expected_qty=Decimal("10.000"),
        received_qty=Decimal("10.000"),
        pending_qty=Decimal("0.000"),
        status="received",
    )

    # 5. Отменённый заказ — должен быть ИСКЛЮЧЁН
    make_purchase_order(
        db_session,
        it_oil1.id,
        loc_msk.id,
        sup1.id,
        doc_number="PO-CANC-01",
        expected_date=date(2026, 9, 22),
        expected_qty=Decimal("30.000"),
        status="cancelled",
    )

    # 6. Заказ для другого склада (LOC-SPB)
    make_purchase_order(
        db_session,
        it_oil1.id,
        loc_spb.id,
        sup1.id,
        doc_number="PO-SPB-01",
        expected_date=date(2026, 9, 26),
        expected_qty=Decimal("7.000"),
    )

    # Проверка с фильтром по объекту LOC-MSK
    snapshot_msk = load_plan_database_snapshot(
        session=db_session,
        as_of=as_of,
        location_code=loc_msk.code,
    )

    msk_docs = [o.doc_number for o in snapshot_msk.existing_orders]
    assert msk_docs == ["PO-DEL-01", "PO-ACT-01", "PO-PART-01"]
    assert "PO-REC-01" not in msk_docs
    assert "PO-CANC-01" not in msk_docs
    assert "PO-SPB-01" not in msk_docs

    part_order = next(o for o in snapshot_msk.existing_orders if o.doc_number == "PO-PART-01")
    assert part_order.pending_qty == Decimal("8.000")
    assert part_order.sku == it_oil1.sku
    assert part_order.location == loc_msk.code
    assert part_order.supplier_id == sup1.supplier_id

    # Проверка без фильтров: присутствуют ровно 4 заказа без дублирования
    snapshot_all = load_plan_database_snapshot(
        session=db_session,
        as_of=as_of,
    )
    all_docs = [o.doc_number for o in snapshot_all.existing_orders]
    assert len(all_docs) == 4
    assert len(set(all_docs)) == 4
    assert "PO-SPB-01" in all_docs


def test_api_existing_orders_filters(
    client: TestClient,
    db_session: Session,
    catalog_setup: dict[str, list],
) -> None:
    """Проверка возврата действующих заказов через POST /api/procurement/plan с фильтрами."""
    it_oil1 = catalog_setup["items"][0]
    it_crm1 = catalog_setup["items"][1]
    loc_msk = catalog_setup["locations"][0]
    loc_spb = catalog_setup["locations"][1]
    sup1 = catalog_setup["suppliers"][0]

    # Заказ для масла в Москве
    make_purchase_order(
        db_session,
        it_oil1.id,
        loc_msk.id,
        sup1.id,
        doc_number="PO-OIL-MSK",
        expected_date=date(2026, 10, 1),
        expected_qty=Decimal("12.000"),
    )
    # Заказ для крема в СПб
    make_purchase_order(
        db_session,
        it_crm1.id,
        loc_spb.id,
        sup1.id,
        doc_number="PO-CRM-SPB",
        expected_date=date(2026, 10, 5),
        expected_qty=Decimal("25.000"),
    )

    # 1. Фильтр location=LOC-MSK
    resp_msk = client.post(
        "/api/procurement/plan",
        json={"horizon_months": 3, "location": loc_msk.code},
    )
    assert resp_msk.status_code == 200
    orders_msk = resp_msk.json()["existing_orders"]
    assert len(orders_msk) == 1
    assert orders_msk[0]["doc_number"] == "PO-OIL-MSK"
    assert orders_msk[0]["sku"] == it_oil1.sku

    # 2. Фильтр category=Кремы
    resp_crm = client.post(
        "/api/procurement/plan",
        json={"horizon_months": 3, "category": "Кремы"},
    )
    assert resp_crm.status_code == 200
    orders_crm = resp_crm.json()["existing_orders"]
    assert len(orders_crm) == 1
    assert orders_crm[0]["doc_number"] == "PO-CRM-SPB"
    assert orders_crm[0]["location"] == loc_spb.code

    # 3. Без фильтров: оба заказа
    resp_all = client.post(
        "/api/procurement/plan",
        json={"horizon_months": 3},
    )
    assert resp_all.status_code == 200
    orders_all = resp_all.json()["existing_orders"]
    assert len(orders_all) == 2
