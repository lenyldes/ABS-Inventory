"""Проверки читающего HTTP-статуса демонабора."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.demo_data.bootstrap import bootstrap_demo_data
from app.demo_data.inspection import get_existing_demo_keys
from app.main import app


@contextmanager
def read_only_request() -> Iterator[None]:
    """Отказывает при любой попытке записи со стороны проверяемого маршрута."""

    def check_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        first_word = statement.lstrip().split(maxsplit=1)[0].upper()
        assert first_word in {"SELECT", "SHOW"}, statement

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", check_sql)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", check_sql)


def request_status() -> tuple[int, dict]:
    with read_only_request(), TestClient(app) as client:
        response = client.get("/api/demo/status")
    return response.status_code, response.json()


def test_status_returns_exact_date_after_loading(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr("app.demo_data.bootstrap.today_in_moscow", lambda: date(2026, 9, 29))
    bootstrap_demo_data(db_session)

    assert request_status() == (200, {"ready": True, "as_of": "2026-09-29"})


def test_status_unavailable_for_empty_set(db_session: Session) -> None:
    status, _body = request_status()
    assert status == 503
    assert not any(get_existing_demo_keys(db_session).values())


def test_status_unavailable_for_incomplete_set(db_session: Session) -> None:
    bootstrap_demo_data(db_session)
    order_key = sorted(get_existing_demo_keys(db_session)["orders"])[0]
    db_session.execute(
        text("DELETE FROM purchase_orders WHERE doc_number = :doc_number"),
        {"doc_number": order_key},
    )
    db_session.commit()
    incomplete_keys = get_existing_demo_keys(db_session)

    status, _body = request_status()
    assert status == 503
    assert get_existing_demo_keys(db_session) == incomplete_keys
