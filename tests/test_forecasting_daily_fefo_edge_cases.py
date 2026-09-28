"""Граничные тесты чистых календарных и суточных расчётов FEFO (задача 2.1)."""

from datetime import date
from decimal import Decimal

import pytest

from app.forecasting.daily_fefo import simulate_daily_fefo
from app.forecasting.domain import IncomingOrderSnapshot
from app.inventory.domain import BatchSnapshot


def _make_batch(
    batch_id: int,
    receipt_date: date,
    expiry_date: date | None,
) -> BatchSnapshot:
    """Вспомогательная фабрика учётных партий для тестов."""
    return BatchSnapshot(
        id=batch_id,
        item_id=1,
        location_id=1,
        batch_number=f"B-{batch_id}",
        receipt_date=receipt_date,
        expiry_date=expiry_date,
        unit_price=Decimal("100.00"),
        receipt_doc_number=f"DOC-{batch_id}",
    )


def test_month_boundary_horizon_leap_and_non_leap() -> None:
    """Проверка границ горизонта на стыке месяцев в високосный и невисокосный годы."""
    # Невисокосный год: 31.01.2025 -> февраль (28 дней)
    res_non_leap = simulate_daily_fefo(
        as_of=date(2025, 1, 31),
        average_daily_consumption=Decimal("1.000"),
        batches=[],
        horizon_months=1,
    )
    assert res_non_leap.horizon_start == date(2025, 2, 1)
    assert res_non_leap.horizon_end == date(2025, 2, 28)
    assert res_non_leap.days_count == 28
    assert len(res_non_leap.daily_steps) == 28

    # Високосный год: 31.01.2024 -> февраль (29 дней)
    res_leap = simulate_daily_fefo(
        as_of=date(2024, 1, 31),
        average_daily_consumption=Decimal("1.000"),
        batches=[],
        horizon_months=1,
    )
    assert res_leap.horizon_start == date(2024, 2, 1)
    assert res_leap.horizon_end == date(2024, 2, 29)
    assert res_leap.days_count == 29
    assert len(res_leap.daily_steps) == 29


def test_zero_consumption_behavior() -> None:
    """При нулевом расходе stockout_date равен None, остаток не списывается в расход."""
    as_of = date(2026, 10, 1)
    b = _make_batch(1, date(2026, 9, 1), date(2026, 10, 10))
    res = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("0.000"),
        batches=[b],
        batch_stocks={1: Decimal("5.000")},
        horizon_days=5,
    )
    assert res.stockout_date is None
    assert res.first_deficit_date is None
    assert res.total_consumption == Decimal("0.000")
    assert res.total_deficit == Decimal("0.000")
    assert res.has_temporary_stockout is False
    assert all(s.closing_stock == Decimal("5.000") for s in res.daily_steps)


def test_delayed_incoming_orders_ignored() -> None:
    """Поставки с expected_date <= as_of считаются задержанными и не учитываются."""
    as_of = date(2026, 10, 1)
    delayed = [
        IncomingOrderSnapshot(
            order_id=1,
            doc_number="PO-OLD",
            expected_date=date(2026, 10, 1),
            pending_qty=Decimal("10.000"),
        )
    ]
    res = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("1.000"),
        batches=[],
        incoming_orders=delayed,
        horizon_days=2,
    )
    assert res.total_incoming == Decimal("0.000")
    assert res.first_deficit_date == date(2026, 10, 2)


def test_negative_consumption_raises_error() -> None:
    """Отрицательный среднесуточный расход недопустим."""
    with pytest.raises(ValueError, match="не может быть отрицательным"):
        simulate_daily_fefo(
            as_of=date(2026, 10, 1),
            average_daily_consumption=Decimal("-1.000"),
            batches=[],
            horizon_days=3,
        )
