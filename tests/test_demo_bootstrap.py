"""Проверки автоматической подготовки демонабора без пересборки."""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.demo_data import bootstrap
from app.demo_data.inspection import get_existing_demo_keys, require_demo_as_of


def test_bootstrap_creates_once_and_preserves_other_data(
    db_session: Session, monkeypatch, capsys
) -> None:
    db_session.execute(
        text("INSERT INTO locations (code, name) VALUES (:code, :name)"),
        {"code": "USER-LOCATION", "name": "Пользовательский объект"},
    )
    db_session.commit()

    monkeypatch.setattr(bootstrap, "today_in_moscow", lambda: date(2026, 9, 29))
    assert bootstrap.bootstrap_demo_data(db_session) == date(2026, 9, 29)
    first_keys = get_existing_demo_keys(db_session)
    first_movements = db_session.execute(text("SELECT count(*) FROM movements")).scalar_one()
    assert require_demo_as_of(db_session) == date(2026, 9, 29)

    monkeypatch.setattr(bootstrap, "today_in_moscow", lambda: date(2026, 9, 30))
    assert bootstrap.bootstrap_demo_data(db_session) == date(2026, 9, 29)
    assert get_existing_demo_keys(db_session) == first_keys
    assert (
        db_session.execute(text("SELECT count(*) FROM movements")).scalar_one() == first_movements
    )
    assert (
        db_session.execute(
            text("SELECT name FROM locations WHERE code = 'USER-LOCATION'")
        ).scalar_one()
        == "Пользовательский объект"
    )
    assert capsys.readouterr().err == ""


def test_bootstrap_rejects_missing_key_without_writing(db_session: Session, capsys) -> None:
    bootstrap.bootstrap_demo_data(db_session)
    order_key = sorted(get_existing_demo_keys(db_session)["orders"])[0]
    db_session.execute(
        text("DELETE FROM purchase_orders WHERE doc_number = :doc_number"),
        {"doc_number": order_key},
    )
    db_session.commit()
    incomplete_keys = get_existing_demo_keys(db_session)

    assert bootstrap.main() == 1
    assert get_existing_demo_keys(db_session) == incomplete_keys
    error = capsys.readouterr().err
    assert order_key in error
    assert "postgresql" not in error.lower()
