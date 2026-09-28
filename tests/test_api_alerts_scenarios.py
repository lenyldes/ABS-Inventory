"""HTTP-интеграционные сценарии эндпоинта GET /api/alerts: сортировка, пагинация, горизонты."""

from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import timezone as app_timezone
from app.inventory.operations import register_consume, register_receipt
from app.main import app
from app.models.catalog import Item, Location, Supplier
from tests.forecasting_fixtures import make_purchase_order, make_supplier_condition


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def test_get_alerts_pagination_and_sorting(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Проверка стабильной сортировки (critical -> warning -> info) и пагинации."""
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 28)

    # Создаём условия поставщика
    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        lead_time_days=5,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("1.000"),
    )

    # 1. Просроченная партия (critical)
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-PAG-01",
        batch_number="B-PAG-01",
        expiry_date=as_of - timedelta(days=2),
        unit_price=Decimal("100.00"),
    )
    # 2. Скоропорт (warning)
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("10.000"),
        doc_number="REC-PAG-02",
        batch_number="B-PAG-02",
        expiry_date=as_of + timedelta(days=10),
        unit_price=Decimal("100.00"),
    )
    db_session.commit()

    base_params = {
        "as_of": as_of.isoformat(),
        "sku": item.sku,
        "location": location.code,
    }

    # Запрос без пагинации
    r_all = client.get("/api/alerts", params={**base_params, "limit": 100})
    assert r_all.status_code == 200
    all_data = r_all.json()
    total = all_data["total"]
    assert total >= 2

    # Проверка сортировки: critical должны идти до warning
    levels = [it["level"] for it in all_data["items"]]
    order_map = {"critical": 0, "warning": 1, "info": 2}
    order_indices = [order_map.get(lvl, 99) for lvl in levels]
    assert order_indices == sorted(order_indices)

    # Проверка пагинации: страница 1 и страница 2
    r_p1 = client.get("/api/alerts", params={**base_params, "limit": 1, "offset": 0})
    assert r_p1.status_code == 200
    data_p1 = r_p1.json()
    assert len(data_p1["items"]) == 1
    assert data_p1["total"] == total
    assert data_p1["items"][0]["id"] == all_data["items"][0]["id"]

    r_p2 = client.get("/api/alerts", params={**base_params, "limit": 1, "offset": 1})
    assert r_p2.status_code == 200
    data_p2 = r_p2.json()
    assert len(data_p2["items"]) == 1
    assert data_p2["items"][0]["id"] == all_data["items"][1]["id"]


def test_get_alerts_horizon_days(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Проверка динамического горизонта max(30, lead_time+1) и явного horizon_days в metrics."""
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 28)

    # Срок поставки 45 дней -> динамический горизонт max(30, 45 + 1) = 46 дней
    make_supplier_condition(
        db_session,
        item.id,
        supplier.id,
        lead_time_days=45,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("1.000"),
    )

    # Поступление и расход, приводящие к нулевому остатку при наличии расхода -> дефицит
    register_receipt(
        db_session,
        item=item,
        location=location,
        operation_date=as_of - timedelta(days=60),
        quantity=Decimal("100.000"),
        doc_number="REC-HOR-1",
        batch_number="B-HOR-1",
        expiry_date=as_of + timedelta(days=100),
        unit_price=Decimal("100.00"),
    )
    register_consume(
        db_session,
        item=item,
        location=location,
        operation_date=as_of - timedelta(days=5),
        quantity=Decimal("100.000"),
        doc_number="CON-HOR-1",
    )
    db_session.commit()

    base_params = {
        "as_of": as_of.isoformat(),
        "sku": item.sku,
        "location": location.code,
        "type": "stockout",
    }

    # 1. Без horizon_days -> динамический горизонт = 46 дней
    r_dyn = client.get("/api/alerts", params=base_params)
    assert r_dyn.status_code == 200
    dyn_items = r_dyn.json()["items"]
    assert len(dyn_items) == 1
    metrics_dyn = dyn_items[0]["metrics"]
    assert metrics_dyn["horizon_days"] == 46
    assert metrics_dyn["horizon_end"] == (as_of + timedelta(days=46)).isoformat()

    # 2. С явным horizon_days=7 -> горизонт = 7 дней
    r_exp = client.get("/api/alerts", params={**base_params, "horizon_days": 7})
    assert r_exp.status_code == 200
    exp_items = r_exp.json()["items"]
    assert len(exp_items) == 1
    metrics_exp = exp_items[0]["metrics"]
    assert metrics_exp["horizon_days"] == 7
    assert metrics_exp["horizon_end"] == (as_of + timedelta(days=7)).isoformat()


def test_get_alerts_incomplete_history_before_first_receipt(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
) -> None:
    """Заказ без складских операций показывает отсутствие истории на дату запроса."""
    item, location, supplier = base_catalog
    as_of = date(2026, 9, 28)
    make_purchase_order(
        db_session,
        item_id=item.id,
        location_id=location.id,
        supplier_id=supplier.id,
        doc_number="PO-BEFORE-RECEIPT",
        expected_date=as_of + timedelta(days=5),
        expected_qty=Decimal("10.000"),
    )

    response = client.get(
        "/api/alerts",
        params={
            "as_of": as_of.isoformat(),
            "sku": item.sku,
            "location": location.code,
            "type": "incomplete_history",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    alert = data["items"][0]
    assert alert["level"] == "info"
    assert alert["sku"] == item.sku
    assert alert["location"] == location.code
    assert alert["metrics"]["history_days"] == 0
    assert alert["metrics"]["first_movement_date"] is None


def test_get_alerts_default_as_of_uses_moscow_date(
    client: TestClient,
    db_session: Session,
    base_catalog: tuple[Item, Location, Supplier],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """На границе суток UTC дата по умолчанию соответствует Москве."""
    item, location, supplier = base_catalog
    fixed_utc = datetime(2026, 9, 27, 21, 30, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            assert tz == app_timezone.MOSCOW_TZ
            return fixed_utc.astimezone(tz)

    monkeypatch.setattr(app_timezone, "datetime", FixedDateTime)
    make_purchase_order(
        db_session,
        item_id=item.id,
        location_id=location.id,
        supplier_id=supplier.id,
        doc_number="PO-DEFAULT-AS-OF",
        expected_date=date(2026, 9, 29),
        expected_qty=Decimal("10.000"),
    )

    response = client.get(
        "/api/alerts",
        params={"sku": item.sku, "location": location.code, "type": "incomplete_history"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["as_of"] == "2026-09-28"
