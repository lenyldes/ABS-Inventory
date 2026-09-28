"""Тесты чистых календарных и суточных расчётов FEFO (задача 2.1)."""

from datetime import date, datetime
from decimal import Decimal

from app.forecasting.daily_fefo import simulate_daily_fefo
from app.forecasting.domain import IncomingOrderSnapshot
from app.inventory.domain import BatchSnapshot


def _make_batch(
    batch_id: int,
    receipt_date: date,
    expiry_date: date | None,
    created_at: datetime | None = None,
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
        created_at=created_at or datetime(2026, 9, 1, 10, 0),
    )


def test_daily_fefo_spec_scenario_with_expiry_and_temporary_deficit() -> None:
    """Сценарий спецификации: просрочка, дефицит и приход поставки."""
    as_of = date(2026, 10, 1)
    b1 = _make_batch(1, date(2026, 9, 20), date(2026, 10, 2))
    b2 = _make_batch(2, date(2026, 9, 25), date(2026, 10, 10))
    batch_stocks = {1: Decimal("3.000"), 2: Decimal("2.000")}

    incoming = [
        IncomingOrderSnapshot(
            order_id=101,
            doc_number="PO-101",
            expected_date=date(2026, 10, 5),
            pending_qty=Decimal("4.000"),
        )
    ]

    res = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("2.000"),
        batches=[b1, b2],
        batch_stocks=batch_stocks,
        incoming_orders=incoming,
        horizon_days=5,
    )

    assert res.horizon_start == date(2026, 10, 2)
    assert res.horizon_end == date(2026, 10, 6)
    assert res.days_count == 5
    assert len(res.daily_steps) == 5

    # 02.10: расход 2 из b1; closing = 1 (b1) + 2 (b2) = 3
    s1 = res.daily_steps[0]
    assert s1.date == date(2026, 10, 2)
    assert s1.expired == Decimal("0.000")
    assert s1.incoming == Decimal("0.000")
    assert s1.consumption == Decimal("2.000")
    assert s1.closing_stock == Decimal("3.000")
    assert s1.daily_deficit == Decimal("0.000")

    # 03.10: 1 ед. b1 просрочена, расход 2 из b2; closing = 0
    s2 = res.daily_steps[1]
    assert s2.date == date(2026, 10, 3)
    assert s2.expired == Decimal("1.000")
    assert s2.incoming == Decimal("0.000")
    assert s2.consumption == Decimal("2.000")
    assert s2.closing_stock == Decimal("0.000")
    assert s2.daily_deficit == Decimal("0.000")

    # 04.10: дефицит 2 ед., остаток 0
    s3 = res.daily_steps[2]
    assert s3.date == date(2026, 10, 4)
    assert s3.expired == Decimal("0.000")
    assert s3.incoming == Decimal("0.000")
    assert s3.consumption == Decimal("0.000")
    assert s3.closing_stock == Decimal("0.000")
    assert s3.daily_deficit == Decimal("2.000")

    # 05.10: приход 4 ед., расход 2 из поставки; closing = 2
    s4 = res.daily_steps[3]
    assert s4.date == date(2026, 10, 5)
    assert s4.expired == Decimal("0.000")
    assert s4.incoming == Decimal("4.000")
    assert s4.consumption == Decimal("2.000")
    assert s4.closing_stock == Decimal("2.000")
    assert s4.daily_deficit == Decimal("0.000")

    # 06.10: расход 2 из остатка поставки; closing = 0
    s5 = res.daily_steps[4]
    assert s5.date == date(2026, 10, 6)
    assert s5.expired == Decimal("0.000")
    assert s5.incoming == Decimal("0.000")
    assert s5.consumption == Decimal("2.000")
    assert s5.closing_stock == Decimal("0.000")
    assert s5.daily_deficit == Decimal("0.000")

    # Сводные агрегаты
    assert res.stockout_date == date(2026, 10, 3)
    assert res.first_deficit_date == date(2026, 10, 4)
    assert res.total_incoming == Decimal("4.000")
    assert res.total_consumption == Decimal("8.000")
    assert res.total_expired == Decimal("1.000")
    assert res.total_deficit == Decimal("2.000")
    assert res.has_temporary_stockout is True


def test_batch_expiration_scenario() -> None:
    """Партия 10 ед. годна 2 дня: расход 1 ед./день, списание остатка 8 ед."""
    as_of = date(2026, 9, 10)
    b = _make_batch(1, date(2026, 9, 1), date(2026, 9, 12))
    res = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("1.000"),
        batches=[b],
        batch_stocks={1: Decimal("10.000")},
        horizon_days=5,
    )

    # 11.09: cons=1, closing=9
    assert res.daily_steps[0].consumption == Decimal("1.000")
    assert res.daily_steps[0].closing_stock == Decimal("9.000")
    assert res.daily_steps[0].expired == Decimal("0.000")

    # 12.09: cons=1, closing=8
    assert res.daily_steps[1].consumption == Decimal("1.000")
    assert res.daily_steps[1].closing_stock == Decimal("8.000")
    assert res.daily_steps[1].expired == Decimal("0.000")

    # 13.09: 8 ед. списано по сроку, cons=0, def=1
    assert res.daily_steps[2].expired == Decimal("8.000")
    assert res.daily_steps[2].consumption == Decimal("0.000")
    assert res.daily_steps[2].closing_stock == Decimal("0.000")
    assert res.daily_steps[2].daily_deficit == Decimal("1.000")

    assert res.total_expired == Decimal("8.000")
    assert res.first_deficit_date == date(2026, 9, 13)


def test_temporary_stockout_flag_distinction() -> None:
    """Проверка различия временного дефицита до поставки и дефицита после поставок."""
    as_of = date(2026, 10, 1)

    # Случай А: дефицит возник до поставки -> has_temporary_stockout=True
    inc_later = [
        IncomingOrderSnapshot(
            order_id=1,
            doc_number="PO-1",
            expected_date=date(2026, 10, 4),
            pending_qty=Decimal("5.000"),
        )
    ]
    res_gap = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("2.000"),
        batches=[],
        incoming_orders=inc_later,
        horizon_days=5,
    )
    # 02.10 и 03.10 дефицит, 04.10 приход
    assert res_gap.first_deficit_date == date(2026, 10, 2)
    assert res_gap.has_temporary_stockout is True

    # Случай Б: поставка в день 1 (02.10), затем исчерпание и дефицит в день 4 -> False
    inc_early = [
        IncomingOrderSnapshot(
            order_id=2,
            doc_number="PO-2",
            expected_date=date(2026, 10, 2),
            pending_qty=Decimal("4.000"),
        )
    ]
    res_after = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("2.000"),
        batches=[],
        incoming_orders=inc_early,
        horizon_days=5,
    )
    # 02.10 cons 2, 03.10 cons 2, 04.10 def 2; поставок после 04.10 нет
    assert res_after.first_deficit_date == date(2026, 10, 4)
    assert res_after.has_temporary_stockout is False


def test_fefo_priority_with_unlimited_shelf_life_and_incoming() -> None:
    """Партии со сроком годности расходуются первыми, бессрочные и приход — в конце."""
    as_of = date(2026, 10, 1)
    b_exp = _make_batch(1, date(2026, 9, 1), date(2026, 10, 10))
    b_inf = _make_batch(2, date(2026, 9, 2), None)
    batch_stocks = {1: Decimal("2.000"), 2: Decimal("2.000")}

    inc = [
        IncomingOrderSnapshot(
            order_id=1,
            doc_number="PO-1",
            expected_date=date(2026, 10, 2),
            pending_qty=Decimal("2.000"),
        )
    ]

    res = simulate_daily_fefo(
        as_of=as_of,
        average_daily_consumption=Decimal("2.000"),
        batches=[b_inf, b_exp],
        batch_stocks=batch_stocks,
        incoming_orders=inc,
        horizon_days=3,
    )

    # День 1 (02.10): расход 2 должен полностью уйти из b_exp (со сроком)
    # Остаются b_inf (2) и incoming (2), closing = 4
    assert res.daily_steps[0].closing_stock == Decimal("4.000")

    # День 2 (03.10): расход 2 должен уйти из b_inf (складской без срока), closing = 2 (поставка)
    assert res.daily_steps[1].closing_stock == Decimal("2.000")

    # День 3 (04.10): расход 2 уходит из остатка поставки, closing = 0
    assert res.daily_steps[2].closing_stock == Decimal("0.000")
