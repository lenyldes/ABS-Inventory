"""Модульные тесты проверки исторической обеспеченности и валидации возвратов."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)
from app.inventory.exceptions import (
    ExcessReturnError,
    HistoricalSufficiencyError,
)
from app.inventory.history import validate_history_sufficiency


def _batch(
    b_id: int,
    b_num: str,
    rec_date: date,
    exp_date: date | None,
    created_at: datetime | None = None,
) -> BatchSnapshot:
    return BatchSnapshot(
        id=b_id,
        item_id=1,
        location_id=1,
        batch_number=b_num,
        receipt_date=rec_date,
        expiry_date=exp_date,
        unit_price=Decimal("150.00"),
        receipt_doc_number=f"DOC-{b_id}",
        created_at=created_at or datetime(2026, 9, 1, 10, 0),
    )


def test_history_same_day_order_receipt_before_consume() -> None:
    """Приход и расход в один день: приход доступен для расхода независимо от времени создания."""
    b = _batch(1, "B1", date(2026, 9, 5), date(2026, 10, 10))

    # Расход создан раньше (created_at 09:00), приход создан позже (created_at 15:00)
    m_consume = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 5),
        created_at=datetime(2026, 9, 5, 9, 0),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("2.000"),
        doc_number="CONS-1",
        allocations=(
            AllocationSnapshot(
                batch_id=1,
                quantity=Decimal("2.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )
    m_rec = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 5),
        created_at=datetime(2026, 9, 5, 15, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="REC-1",
        batch_id=1,
    )

    # Бизнес-приоритет receipt ставит его перед consume -> дефицита нет
    validate_history_sufficiency(batches=[b], existing_movements=[m_consume, m_rec])


def test_history_retrospective_consume_creates_intermediate_deficit() -> None:
    """Расход задним числом, создающий дефицит на последующую дату, отклоняется."""
    b = _batch(1, "B1", date(2026, 9, 1), date(2026, 10, 10))

    m_rec = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    m_consume_later = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 3),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("8.000"),
        doc_number="CONS-LATER",
        allocations=(
            AllocationSnapshot(
                batch_id=1,
                quantity=Decimal("8.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )

    # Пытаемся добавить задним числом на 2026-09-02 расход 5.000:
    # 2026-09-01: 10
    # 2026-09-02: 10 - 5 = 5
    # 2026-09-03: 5 - 8 = -3 (дефицит!)
    new_consume = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 2),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("5.000"),
        doc_number="CONS-RETRO",
        allocations=(
            AllocationSnapshot(
                batch_id=1,
                quantity=Decimal("5.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )

    with pytest.raises(HistoricalSufficiencyError) as exc_info:
        validate_history_sufficiency(
            batches=[b],
            existing_movements=[m_rec, m_consume_later],
            new_movement=new_consume,
        )

    assert exc_info.value.details["deficit_date"] == "2026-09-03"
    assert exc_info.value.details["conflicting_doc_number"] == "CONS-LATER"


def test_history_return_limit_and_excess() -> None:
    """Возврат ограничен выданным количеством по строке расхода."""
    b = _batch(1, "B1", date(2026, 9, 1), date(2026, 10, 10))
    m_rec = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    m_consume = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 2),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("3.000"),
        doc_number="CONS-1",
        allocations=(
            AllocationSnapshot(
                id=101,
                batch_id=1,
                quantity=Decimal("3.000"),
                unit_price=Decimal("150.00"),
            ),
        ),
    )

    # Возврат 1.000 допустим
    m_ret1 = MovementSnapshot(
        id=3,
        operation_date=date(2026, 9, 3),
        item_id=1,
        location_id=1,
        type="return",
        quantity=Decimal("1.000"),
        doc_number="RET-1",
        batch_id=1,
        parent_movement_id=2,
        parent_allocation_id=101,
    )
    validate_history_sufficiency(batches=[b], existing_movements=[m_rec, m_consume, m_ret1])

    # Попытка вернуть ещё 2.500 при остатке 2.000 вызывает ExcessReturnError
    m_ret2 = MovementSnapshot(
        id=4,
        operation_date=date(2026, 9, 4),
        item_id=1,
        location_id=1,
        type="return",
        quantity=Decimal("2.500"),
        doc_number="RET-2",
        batch_id=1,
        parent_movement_id=2,
        parent_allocation_id=101,
    )
    with pytest.raises(ExcessReturnError) as exc_info:
        validate_history_sufficiency(
            batches=[b],
            existing_movements=[m_rec, m_consume, m_ret1],
            new_movement=m_ret2,
        )
    assert exc_info.value.details["max_allowed_return"] == "2.000"
