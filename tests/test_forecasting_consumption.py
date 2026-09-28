"""Тесты чистого расчёта расхода за 90 дней, полноты истории и дней запаса."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.forecasting.consumption import calculate_consumption_metrics
from app.inventory.domain import MovementSnapshot


def _mv(
    *,
    op_date: date,
    mv_type: str = "consume",
    qty: Decimal = Decimal("1.000"),
    mv_id: int = 1,
    status: str = "active",
    parent_id: int | None = None,
) -> MovementSnapshot:
    """Вспомогательная функция формирования MovementSnapshot."""
    return MovementSnapshot(
        id=mv_id,
        operation_date=op_date,
        item_id=1,
        location_id=1,
        type=mv_type,
        quantity=qty,
        doc_number=f"DOC-{mv_id}",
        status=status,
        parent_movement_id=parent_id,
    )


def test_consumption_empty_history():
    """Пустая история движений возвращает нулевые метрики и None для запаса."""
    as_of = date(2026, 9, 15)
    res = calculate_consumption_metrics([], as_of=as_of, available_stock=Decimal("10.000"))

    assert res.total_consumption_90d == Decimal("0.000")
    assert res.average_daily_consumption == Decimal("0.000000")
    assert res.history_days == 0
    assert res.is_history_complete is False
    assert res.first_movement_date is None
    assert res.days_of_stock is None


def test_consumption_short_history():
    """Короткая история (30 дней): знаменатель всегда 90, история неполная."""
    as_of = date(2026, 9, 30)
    receipt_date = as_of - timedelta(days=30)
    consume_date = as_of - timedelta(days=10)

    movements = [
        _mv(mv_id=1, op_date=receipt_date, mv_type="receipt", qty=Decimal("50.000")),
        _mv(mv_id=2, op_date=consume_date, mv_type="consume", qty=Decimal("30.000")),
    ]

    res = calculate_consumption_metrics(movements, as_of=as_of, available_stock=Decimal("20.000"))

    assert res.first_movement_date == receipt_date
    assert res.history_days == 30
    assert res.is_history_complete is False
    assert res.total_consumption_90d == Decimal("30.000")
    assert res.average_daily_consumption == Decimal("0.333333")
    assert res.days_of_stock == Decimal("60.0")


@pytest.mark.parametrize(
    ("days_ago", "expected_history_days", "expected_complete"),
    [
        (89, 89, False),
        (90, 90, True),
        (120, 120, True),
    ],
)
def test_consumption_complete_history_boundary(
    days_ago: int,
    expected_history_days: int,
    expected_complete: bool,
):
    """Граничные условия полноты истории (89, 90 и 120 дней)."""
    as_of = date(2026, 9, 30)
    movements = [_mv(mv_id=1, op_date=as_of - timedelta(days=days_ago), mv_type="receipt")]
    res = calculate_consumption_metrics(movements, as_of=as_of)

    assert res.history_days == expected_history_days
    assert res.is_history_complete is expected_complete


def test_consumption_window_boundaries():
    """Проверка границ 90-дневного окна [as_of - 89 дней, as_of]."""
    as_of = date(2026, 9, 30)
    in_start = as_of - timedelta(days=89)
    in_end = as_of
    out_window = as_of - timedelta(days=90)

    movements = [
        _mv(mv_id=1, op_date=out_window, qty=Decimal("100.000")),
        _mv(mv_id=2, op_date=in_start, qty=Decimal("45.000")),
        _mv(mv_id=3, op_date=in_end, qty=Decimal("45.000")),
    ]

    res = calculate_consumption_metrics(movements, as_of=as_of)
    assert res.total_consumption_90d == Decimal("90.000")
    assert res.average_daily_consumption == Decimal("1.000000")
    assert res.first_movement_date == out_window
    assert res.history_days == 90
    assert res.is_history_complete is True


def test_consumption_future_dates_ignored():
    """Движения после as_of не должны влиять на расчёт на контрольную дату."""
    as_of = date(2026, 9, 15)
    movements = [
        _mv(mv_id=1, op_date=as_of, qty=Decimal("10.000")),
        _mv(mv_id=2, op_date=as_of + timedelta(days=1), qty=Decimal("50.000")),
        _mv(
            mv_id=3,
            op_date=as_of + timedelta(days=2),
            mv_type="return",
            qty=Decimal("5.000"),
            parent_id=1,
        ),
    ]

    res = calculate_consumption_metrics(movements, as_of=as_of)
    assert res.total_consumption_90d == Decimal("10.000")
    assert res.first_movement_date == as_of
    assert res.history_days == 0


def test_consumption_return_within_window_as_of_progression():
    """Сценарий спецификации: расход 10.09 (2л), возврат 12.09 (0.5л)."""
    mv_c = _mv(mv_id=1, op_date=date(2026, 9, 10), mv_type="consume", qty=Decimal("2.000"))
    mv_r = _mv(
        mv_id=2,
        op_date=date(2026, 9, 12),
        mv_type="return",
        qty=Decimal("0.500"),
        parent_id=1,
    )
    movements = [mv_c, mv_r]

    res_11 = calculate_consumption_metrics(movements, as_of=date(2026, 9, 11))
    assert res_11.total_consumption_90d == Decimal("2.000")
    assert res_11.average_daily_consumption == Decimal("0.022222")

    res_12 = calculate_consumption_metrics(movements, as_of=date(2026, 9, 12))
    assert res_12.total_consumption_90d == Decimal("1.500")
    assert res_12.average_daily_consumption == Decimal("0.016667")


def test_consumption_return_outside_window_does_not_create_negative():
    """Возврат внутри окна к расходу вне окна не создаёт отрицательного расхода."""
    as_of = date(2026, 9, 30)
    out_date = as_of - timedelta(days=120)

    movements = [
        _mv(mv_id=1, op_date=out_date, mv_type="consume", qty=Decimal("10.000")),
        _mv(
            mv_id=2,
            op_date=as_of - timedelta(days=10),
            mv_type="return",
            qty=Decimal("4.000"),
            parent_id=1,
        ),
    ]

    res = calculate_consumption_metrics(movements, as_of=as_of)
    assert res.total_consumption_90d == Decimal("0.000")
    assert res.average_daily_consumption == Decimal("0.000000")
    assert res.first_movement_date == out_date
    assert res.history_days == 120
    assert res.is_history_complete is True


def test_consumption_multiple_returns_and_cap():
    """Несколько возвратов к одной выдаче и защита от отрицательного расхода."""
    as_of = date(2026, 9, 20)
    movements = [
        _mv(mv_id=1, op_date=as_of - timedelta(days=5), qty=Decimal("10.000")),
        _mv(
            mv_id=2,
            op_date=as_of - timedelta(days=4),
            mv_type="return",
            qty=Decimal("3.000"),
            parent_id=1,
        ),
        _mv(
            mv_id=3,
            op_date=as_of - timedelta(days=3),
            mv_type="return",
            qty=Decimal("2.000"),
            parent_id=1,
        ),
        _mv(mv_id=4, op_date=as_of - timedelta(days=2), qty=Decimal("2.000")),
        _mv(
            mv_id=5,
            op_date=as_of - timedelta(days=1),
            mv_type="return",
            qty=Decimal("3.000"),
            parent_id=4,
        ),
    ]

    res = calculate_consumption_metrics(movements, as_of=as_of)
    # mv 1: 10 - 3 - 2 = 5; mv 4: max(0, 2 - 3) = 0. Итого 5
    assert res.total_consumption_90d == Decimal("5.000")


def test_consumption_other_types_excluded_from_consumption():
    """writeoff и correction не включаются в расход, но определяют первое движение."""
    as_of = date(2026, 9, 25)
    first_date = as_of - timedelta(days=100)

    movements = [
        _mv(mv_id=1, op_date=first_date, mv_type="writeoff", qty=Decimal("10.000")),
        _mv(
            mv_id=2,
            op_date=as_of - timedelta(days=20),
            mv_type="correction",
            qty=Decimal("5.000"),
        ),
    ]

    res = calculate_consumption_metrics(movements, as_of=as_of)
    assert res.total_consumption_90d == Decimal("0.000")
    assert res.average_daily_consumption == Decimal("0.000000")
    assert res.first_movement_date == first_date
    assert res.history_days == 100
    assert res.is_history_complete is True


def test_consumption_inactive_movements_ignored():
    """Отменённые или неактивные движения не влияют на расчёт."""
    as_of = date(2026, 9, 20)
    movements = [
        _mv(
            mv_id=1,
            op_date=as_of - timedelta(days=5),
            status="cancelled",
            qty=Decimal("50.000"),
        ),
        _mv(mv_id=2, op_date=as_of - timedelta(days=3), qty=Decimal("10.000")),
        _mv(
            mv_id=3,
            op_date=as_of - timedelta(days=1),
            mv_type="return",
            status="cancelled",
            qty=Decimal("5.000"),
            parent_id=2,
        ),
    ]

    res = calculate_consumption_metrics(movements, as_of=as_of)
    assert res.total_consumption_90d == Decimal("10.000")
    assert res.first_movement_date == as_of - timedelta(days=3)


@pytest.mark.parametrize(
    ("available_stock", "consumption_qty", "expected_dos"),
    [
        (None, Decimal("90.000"), None),
        (Decimal("15.000"), Decimal("90.000"), Decimal("15.0")),
        (Decimal("0.000"), Decimal("90.000"), Decimal("0.0")),
        (Decimal("10.000"), Decimal("270.000"), Decimal("3.3")),
        (Decimal("4.650"), Decimal("270.000"), Decimal("1.6")),
    ],
)
def test_consumption_days_of_stock_rounding(
    available_stock: Decimal | None,
    consumption_qty: Decimal,
    expected_dos: Decimal | None,
):
    """Проверка расчёта дней запаса и бухгалтерского округления ROUND_HALF_UP."""
    as_of = date(2026, 9, 30)
    movements = [_mv(mv_id=1, op_date=as_of - timedelta(days=10), qty=consumption_qty)]
    res = calculate_consumption_metrics(movements, as_of=as_of, available_stock=available_stock)

    assert res.days_of_stock == expected_dos
