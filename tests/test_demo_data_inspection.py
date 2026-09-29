"""Тесты инспекции и проверки значений записей демонстрационных данных."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.demo_data.inspection import DemoDataError, verify_demo_values
from app.demo_data.loader import prepare_demo_data
from app.demo_data.movements import DEMO_BASE_RECEIPT_DOC
from app.models.inventory import Movement

TEST_AS_OF = date(2026, 9, 29)


def test_verify_demo_values_success(db_session: Session) -> None:
    """Проверяет успешную верификацию эталонных значений после создания демонабора."""
    mode, _ = prepare_demo_data(db_session, as_of=TEST_AS_OF)
    assert mode == "created"

    # Верификация эталона проходит без ошибок
    verify_demo_values(db_session, as_of=TEST_AS_OF)


def test_verify_demo_values_detects_modified_quantity(db_session: Session) -> None:
    """Проверяет обнаружение измененного количества движения при инспекции."""
    prepare_demo_data(db_session, as_of=TEST_AS_OF)

    movement = db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).one()
    movement.quantity = Decimal("999.000")
    db_session.flush()

    with pytest.raises(DemoDataError, match="Несоответствие значений демонстрационного набора"):
        verify_demo_values(db_session, as_of=TEST_AS_OF)


def test_prepare_demo_data_idempotent_fails_on_modified_movement(db_session: Session) -> None:
    """Проверяет отказ возврата idempotent, если количество существующего движения изменено."""
    mode1, _ = prepare_demo_data(db_session, as_of=TEST_AS_OF)
    assert mode1 == "created"

    # Искажаем количество в существующем движении
    movement = db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).one()
    original_qty = movement.quantity
    movement.quantity = original_qty + Decimal("10.000")
    db_session.flush()

    # Повторный вызов на ту же дату должен вызывать ошибку, а не возвращать idempotent
    with pytest.raises(DemoDataError, match="Несоответствие значений"):
        prepare_demo_data(db_session, as_of=TEST_AS_OF)

    # Принудительная пересборка с --replace должна восстановить эталон
    mode_replaced, _ = prepare_demo_data(db_session, as_of=TEST_AS_OF, replace=True)
    assert mode_replaced == "replaced"

    # После replace значения снова корректны
    restored_movement = (
        db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).one()
    )
    assert restored_movement.quantity == original_qty
