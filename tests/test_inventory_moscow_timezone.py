"""Тесты складского API и сервисов при различии календарных дат UTC и Europe/Moscow."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.timezone import today_in_moscow
from app.inventory.common_validation import validate_common_rules
from app.inventory.exceptions import InvalidMovementError
from app.inventory.operations import register_receipt
from app.main import app
from app.models.catalog import Item, Location


class _FrozenMoscowDateTime(datetime):
    """Тестовый класс даты и времени, эмулирующий момент различия дат UTC и Москвы."""

    # 22:30 UTC = 01:30 следующего дня в Europe/Moscow (UTC+3)
    _FROZEN_UTC = datetime(2026, 10, 20, 22, 30, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        if tz is not None:
            return cls._FROZEN_UTC.astimezone(tz)
        return cls._FROZEN_UTC


@pytest.fixture
def freeze_utc_moscow_split():
    """Фиксирует момент времени на 22:30 UTC (2026-10-20), когда в Москве уже 2026-10-21."""
    with patch("app.core.timezone.datetime", _FrozenMoscowDateTime):
        yield


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового клиента FastAPI."""
    return TestClient(app)


def test_today_in_moscow_differs_from_utc(freeze_utc_moscow_split: None) -> None:
    """Проверка базового условия: в UTC ещё вчерашний день, а в Москве уже наступил следующий."""
    utc_date = _FrozenMoscowDateTime._FROZEN_UTC.date()
    moscow_date = today_in_moscow()

    assert utc_date == date(2026, 10, 20)
    assert moscow_date == date(2026, 10, 21)
    assert utc_date != moscow_date


def test_future_date_validation_uses_moscow_date(
    freeze_utc_moscow_split: None,
    db_session: Session,
) -> None:
    """Операция московской датой разрешена в момент, когда в UTC ещё предыдущий день."""
    item = Item(sku="TZ-OIL-01", name="Масло шалфея", category="Масла", unit="л")
    loc = Location(code="TZ-LOC-01", name="SPA Центр")
    db_session.add_all([item, loc])
    db_session.commit()

    # В UTC ещё 2026-10-20, но в Москве уже 2026-10-21: дата 2026-10-21 обязана проходить
    validate_common_rules(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 10, 21),
        quantity=Decimal("5.000"),
        doc_number="DOC-TZ-OK",
    )

    # Дата 2026-10-22 — это будущее относительно Москвы: должна отклоняться с FUTURE_DATE
    with pytest.raises(InvalidMovementError) as exc_info:
        validate_common_rules(
            db_session,
            item=item,
            location=loc,
            operation_date=date(2026, 10, 22),
            quantity=Decimal("5.000"),
            doc_number="DOC-TZ-FUTURE",
        )
    assert exc_info.value.code == "FUTURE_DATE"
    assert exc_info.value.details.get("today") == "2026-10-21"


def test_receipt_balance_and_stock_default_as_of_use_moscow_date(
    freeze_utc_moscow_split: None,
    client: TestClient,
    db_session: Session,
) -> None:
    """Возвращаемый остаток после движения и GET /api/stock без as_of используют дату Москвы."""
    item = Item(sku="TZ-CREAM-01", name="Крем для лица", category="Кремы", unit="шт")
    loc = Location(code="TZ-LOC-02", name="SPA Север")
    db_session.add_all([item, loc])
    db_session.commit()

    # Регистрация прихода с датой 2026-10-21 (которая в UTC была бы завтрашней)
    # Срок годности 2026-10-20: в UTC он считался бы сегодняшним, но в Москве УЖЕ истёк
    res = register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 10, 21),
        quantity=Decimal("10.000"),
        doc_number="DOC-TZ-REC-01",
        batch_number="B-TZ-01",
        expiry_date=date(2026, 10, 20),
        unit_price=Decimal("150.00"),
    )
    db_session.commit()

    # Проверка возвращаемого остатка после движения: вычисляется на московское сегодня (2026-10-21)
    assert res.current_stock == Decimal("10.000")
    # Так как срок годности 2026-10-20 < 2026-10-21, доступный остаток на сегодня равен 0
    assert res.available_stock == Decimal("0.000")

    # Проверка сводного API GET /api/stock без параметра as_of
    resp_summary = client.get(f"/api/stock?sku={item.sku}")
    assert resp_summary.status_code == 200
    summary_data = resp_summary.json()
    assert summary_data["total"] == 1
    stock_item = summary_data["items"][0]
    assert stock_item["current_stock"] == "10.000"
    assert stock_item["available_stock"] == "0.000"
    assert stock_item["expired_stock"] == "10.000"

    # Проверка детального API GET /api/stock/{sku} без параметра as_of
    resp_detail = client.get(f"/api/stock/{item.sku}")
    assert resp_detail.status_code == 200
    detail_data = resp_detail.json()
    loc_detail = detail_data["locations"][0]
    assert loc_detail["current_stock"] == "10.000"
    assert loc_detail["available_stock"] == "0.000"
    assert loc_detail["expired_stock"] == "10.000"
    batch_info = loc_detail["batches"][0]
    assert batch_info["quantity"] == "10.000"
    assert batch_info["available_quantity"] == "0.000"


def test_api_movements_future_date_http_response(
    freeze_utc_moscow_split: None,
    client: TestClient,
    db_session: Session,
) -> None:
    """HTTP API POST /api/movements корректно различает московское сегодня и будущее."""
    item = Item(sku="TZ-SCRUB-01", name="Скраб кофейный", category="Скрабы", unit="шт")
    loc = Location(code="TZ-LOC-03", name="SPA Юг")
    db_session.add_all([item, loc])
    db_session.commit()

    # Операция на московское сегодня (2026-10-21) создаётся успешно
    resp_today = client.post(
        "/api/movements",
        json={
            "type": "receipt",
            "operation_date": "2026-10-21",
            "sku": item.sku,
            "location": loc.code,
            "quantity": "5.000",
            "doc_number": "DOC-TZ-HTTP-01",
            "batch_number": "B-TZ-02",
            "expiry_date": "2027-01-01",
            "unit_price": "500.00",
        },
    )
    assert resp_today.status_code == 201
    assert resp_today.json()["current_stock"] == "5.000"

    # Операция на будущее относительно Москвы (2026-10-22) возвращает 422 FUTURE_DATE
    resp_future = client.post(
        "/api/movements",
        json={
            "type": "receipt",
            "operation_date": "2026-10-22",
            "sku": item.sku,
            "location": loc.code,
            "quantity": "5.000",
            "doc_number": "DOC-TZ-HTTP-02",
            "batch_number": "B-TZ-03",
            "expiry_date": "2027-01-01",
            "unit_price": "500.00",
        },
    )
    assert resp_future.status_code == 422
    err = resp_future.json()
    assert err["code"] == "FUTURE_DATE"
    assert err["details"]["today"] == "2026-10-21"
