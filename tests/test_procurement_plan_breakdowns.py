"""Тесты аналитических разрезов бюджета плана повторных закупок (подзадача 3.1)."""

from datetime import date
from decimal import Decimal

from app.api.plan_schemas import PlanItemSchema
from app.procurement_plan.breakdowns import (
    build_procurement_plan_breakdowns,
    evaluate_budget_limit,
)
from app.procurement_plan.dates import generate_horizon_months


def _make_item(
    sku: str = "SKU-001",
    category: str = "Электроника",
    location: str = "WH-1",
    order_date: date | None = date(2026, 9, 20),
    quantity: Decimal = Decimal("10.000"),
    unit_price: Decimal | None = Decimal("10.01"),
    total_cost: Decimal | None = Decimal("10.01"),
    name: str | None = None,
    location_name: str | None = None,
) -> PlanItemSchema:
    """Вспомогательная фабрика позиции плана для тестов агрегации."""
    return PlanItemSchema(
        sku=sku,
        name=name or f"Товар {sku}",
        category=category,
        location=location,
        location_name=location_name or f"Склад {location}",
        order_date=order_date,
        delivery_date=order_date,
        raw_quantity=quantity,
        quantity=quantity,
        unit_price=unit_price,
        total_cost=total_cost,
    )


def test_breakdowns_sums_and_scenario_equality() -> None:
    """Проверка сценария из spec: 2 датированных (10.01 + 20.02) и 1 недатированная (5.00).

    Сумма по месяцам (30.03) + undated (5.00) == 35.03.
    Разрезы по SKU, категориям и объектам также суммируются в 35.03.
    """
    item1 = _make_item(
        sku="SKU-1",
        category="Кат-A",
        location="WH-1",
        order_date=date(2026, 9, 20),
        quantity=Decimal("1.000"),
        unit_price=Decimal("10.01"),
        total_cost=Decimal("10.01"),
    )
    item2 = _make_item(
        sku="SKU-2",
        category="Кат-B",
        location="WH-2",
        order_date=date(2026, 10, 10),
        quantity=Decimal("2.000"),
        unit_price=Decimal("10.01"),
        total_cost=Decimal("20.02"),
    )
    item3 = _make_item(
        sku="SKU-1",
        category="Кат-A",
        location="WH-2",
        order_date=None,
        quantity=Decimal("0.500"),
        unit_price=Decimal("10.00"),
        total_cost=Decimal("5.00"),
    )

    items = [item1, item2, item3]
    budget = build_procurement_plan_breakdowns(
        items=items,
        as_of=date(2026, 9, 15),
        horizon_months=3,
    )

    assert budget.known_total == Decimal("35.03")
    assert budget.total_cost == Decimal("35.03")
    assert budget.total_quantity == Decimal("3.500")
    assert budget.is_price_complete is True
    assert budget.has_unpriced_items is False
    assert budget.unknown_price_count == 0
    assert budget.undated_count == 1
    assert budget.is_dates_complete is False

    # Суммы по месяцам и недатированным
    month_sum = sum((m.known_total for m in budget.by_month), Decimal("0.00"))
    assert month_sum == Decimal("30.03")
    assert budget.undated.known_total == Decimal("5.00")
    assert month_sum + budget.undated.known_total == budget.known_total

    # Разрезы по SKU, категории и объекту суммируются в общий итог
    sku_sum = sum((s.known_total for s in budget.by_sku), Decimal("0.00"))
    cat_sum = sum((c.known_total for c in budget.by_category), Decimal("0.00"))
    loc_sum = sum((loc.known_total for loc in budget.by_location), Decimal("0.00"))
    assert sku_sum == budget.known_total
    assert cat_sum == budget.known_total
    assert loc_sum == budget.known_total

    # Суммы количеств во всех разрезах совпадают
    month_qty = sum((m.total_quantity for m in budget.by_month), Decimal("0.000"))
    assert month_qty + budget.undated.total_quantity == budget.total_quantity
    sku_qty = sum((s.total_quantity for s in budget.by_sku), Decimal("0.000"))
    cat_qty = sum((c.total_quantity for c in budget.by_category), Decimal("0.000"))
    loc_qty = sum((loc.total_quantity for loc in budget.by_location), Decimal("0.000"))
    assert sku_qty == budget.total_quantity
    assert cat_qty == budget.total_quantity
    assert loc_qty == budget.total_quantity


def test_breakdowns_pennies_precision() -> None:
    """Проверка точности до копеек и отсутствия погрешности с плавающей точкой."""
    items = [
        _make_item(
            order_date=date(2026, 9, 1),
            quantity=Decimal("1.000"),
            total_cost=Decimal("0.01"),
        ),
        _make_item(
            order_date=date(2026, 9, 2),
            quantity=Decimal("1.000"),
            total_cost=Decimal("0.02"),
        ),
        _make_item(
            order_date=date(2026, 9, 3),
            quantity=Decimal("1.000"),
            total_cost=Decimal("0.03"),
        ),
        _make_item(
            order_date=date(2026, 9, 4),
            quantity=Decimal("1.000"),
            total_cost=Decimal("0.04"),
        ),
    ]
    budget = build_procurement_plan_breakdowns(
        items=items,
        as_of=date(2026, 9, 1),
        horizon_months=1,
    )
    assert budget.known_total == Decimal("0.10")
    assert budget.by_month[0].known_total == Decimal("0.10")


def test_breakdowns_unpriced_items_handling() -> None:
    """Проверка обработки позиций без цены (total_cost=None, unit_price=None)."""
    item_priced = _make_item(
        sku="SKU-1",
        order_date=date(2026, 9, 20),
        quantity=Decimal("10.000"),
        total_cost=Decimal("100.50"),
    )
    item_unpriced = _make_item(
        sku="SKU-2",
        order_date=date(2026, 9, 25),
        quantity=Decimal("5.000"),
        unit_price=None,
        total_cost=None,
    )
    budget = build_procurement_plan_breakdowns(
        items=[item_priced, item_unpriced],
        as_of=date(2026, 9, 15),
        horizon_months=1,
    )

    assert budget.known_total == Decimal("100.50")
    assert budget.total_quantity == Decimal("15.000")
    assert budget.is_price_complete is False
    assert budget.has_unpriced_items is True
    assert budget.unknown_price_count == 1
    assert budget.unpriced_items_count == 1

    sept_month = next(m for m in budget.by_month if m.month == "2026-09")
    assert sept_month.items_count == 2
    assert sept_month.total_quantity == Decimal("15.000")
    assert sept_month.known_total == Decimal("100.50")
    assert sept_month.has_unpriced_items is True
    assert sept_month.is_price_complete is False

    sku2 = next(s for s in budget.by_sku if s.sku == "SKU-2")
    assert sku2.has_unpriced_items is True
    assert sku2.is_price_complete is False
    assert sku2.known_total == Decimal("0.00")
    assert sku2.total_quantity == Decimal("5.000")


def test_partial_months_detection() -> None:
    """Проверка флагов неполных первого и последнего календарных месяцев."""
    # 1. 15.09 - 15.12 (3 месяца): сентябрь и декабрь частичные, октябрь и ноябрь полные
    months_3m = generate_horizon_months(as_of=date(2026, 9, 15), horizon_end=date(2026, 12, 15))
    dict_3m = {m[0]: m[3] for m in months_3m}
    assert dict_3m["2026-09"] is True
    assert dict_3m["2026-10"] is False
    assert dict_3m["2026-11"] is False
    assert dict_3m["2026-12"] is True

    # 2. 31.01 - 28.02 (1 месяц): январь частичный (день 31 != 1), февраль полный (день 28 == 28)
    months_end = generate_horizon_months(as_of=date(2026, 1, 31), horizon_end=date(2026, 2, 28))
    dict_end = {m[0]: m[3] for m in months_end}
    assert dict_end["2026-01"] is True
    assert dict_end["2026-02"] is False

    # 3. 01.09 - 01.10 (1 месяц): сентябрь полный (день 1), октябрь частичный (день 1 != 31)
    months_start = generate_horizon_months(as_of=date(2026, 9, 1), horizon_end=date(2026, 10, 1))
    dict_start = {m[0]: m[3] for m in months_start}
    assert dict_start["2026-09"] is False
    assert dict_start["2026-10"] is True


def test_empty_items_budget() -> None:
    """Проверка расчёта разрезов для пустого списка позиций."""
    budget = build_procurement_plan_breakdowns(
        items=[],
        as_of=date(2026, 9, 15),
        horizon_months=1,
    )
    assert budget.known_total == Decimal("0.00")
    assert budget.total_quantity == Decimal("0.000")
    assert budget.is_price_complete is True
    assert budget.has_unpriced_items is False
    assert budget.is_dates_complete is True
    assert budget.undated_count == 0
    assert budget.by_sku == []
    assert budget.by_category == []
    assert budget.by_location == []
    assert len(budget.by_month) >= 1
    assert budget.by_month[0].items_count == 0
    assert budget.by_month[0].known_total == Decimal("0.00")


def test_budget_limit_evaluation() -> None:
    """Проверка статусов лимита: within, exceeded, undetermined."""
    # within при полной цене
    st, diff = evaluate_budget_limit(Decimal("900.00"), Decimal("1000.00"), is_price_complete=True)
    assert st == "within"
    assert diff == Decimal("-100.00")

    # exceeded
    st, diff = evaluate_budget_limit(Decimal("1100.00"), Decimal("1000.00"), is_price_complete=True)
    assert st == "exceeded"
    assert diff == Decimal("100.00")

    # undetermined при неполной цене и сумме не выше лимита
    st, diff = evaluate_budget_limit(Decimal("900.00"), Decimal("1000.00"), is_price_complete=False)
    assert st == "undetermined"
    assert diff == Decimal("-100.00")

    # exceeded даже при неполной цене, если известная сумма уже превысила лимит
    st, diff = evaluate_budget_limit(
        Decimal("1200.00"), Decimal("1000.00"), is_price_complete=False
    )
    assert st == "exceeded"
    assert diff == Decimal("200.00")
