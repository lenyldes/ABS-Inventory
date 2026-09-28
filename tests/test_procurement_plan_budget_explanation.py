"""Тесты сравнения с лимитом бюджета и объяснения плана закупок (подзадача 3.2)."""

from datetime import date
from decimal import Decimal

from app.api.plan_schemas import PlanItemSchema
from app.procurement_plan.breakdowns import (
    build_procurement_plan_breakdowns,
    evaluate_budget_limit,
)
from app.procurement_plan.explanation import build_plan_explanation
from app.procurement_plan.explanation_templates import get_incompleteness_reasons
from app.procurement_plan.warnings import (
    WARN_DELIVERY_BEYOND_HORIZON,
    WARN_INCOMPLETE_HISTORY,
    WARN_LEAD_TIME_UNKNOWN,
    WARN_ORDER_DELAYED,
    WARN_PRICE_UNKNOWN,
    WARN_TEMPORARY_DEFICIT,
)


def _item(
    sku: str = "SKU-1",
    category: str = "Кат-A",
    location: str = "WH-1",
    order_date: date | None = date(2026, 9, 20),
    quantity: Decimal = Decimal("10.000"),
    unit_price: Decimal | None = Decimal("100.00"),
    total_cost: Decimal | None = Decimal("1000.00"),
    warnings: list[str] | None = None,
) -> PlanItemSchema:
    """Фабрика позиции плана для тестов объяснения и лимита."""
    return PlanItemSchema(
        sku=sku,
        name=f"Товар {sku}",
        category=category,
        location=location,
        order_date=order_date,
        delivery_date=order_date,
        raw_quantity=quantity,
        quantity=quantity,
        unit_price=unit_price,
        total_cost=total_cost,
        warnings=warnings or [],
    )


def test_budget_limit_statuses_and_differences() -> None:
    """Проверка статусов exceeded, within, undetermined и разницы с лимитом."""
    # 1. Лимит не задан
    status, diff = evaluate_budget_limit(Decimal("500.00"), None, is_price_complete=True)
    assert status is None and diff is None

    # 2. within: known_total <= budget_limit при полной цене
    status, diff = evaluate_budget_limit(
        Decimal("900.00"), Decimal("1000.00"), is_price_complete=True
    )
    assert status == "within" and diff == Decimal("-100.00")

    # 3. within при точном равенстве сумм и полной цене
    status, diff = evaluate_budget_limit(
        Decimal("1000.00"), Decimal("1000.00"), is_price_complete=True
    )
    assert status == "within" and diff == Decimal("0.00")

    # 4. exceeded: known_total > budget_limit
    status, diff = evaluate_budget_limit(
        Decimal("1100.00"), Decimal("1000.00"), is_price_complete=True
    )
    assert status == "exceeded" and diff == Decimal("100.00")

    # 5. undetermined: known_total <= budget_limit при неполных ценах
    status, diff = evaluate_budget_limit(
        Decimal("900.00"), Decimal("1000.00"), is_price_complete=False
    )
    assert status == "undetermined" and diff == Decimal("-100.00")

    # 6. undetermined при точном равенстве сумм и неполных ценах
    status, diff = evaluate_budget_limit(
        Decimal("1000.00"), Decimal("1000.00"), is_price_complete=False
    )
    assert status == "undetermined" and diff == Decimal("0.00")

    # 7. exceeded даже при неполных ценах, если известная часть превысила лимит
    status, diff = evaluate_budget_limit(
        Decimal("1200.00"), Decimal("1000.00"), is_price_complete=False
    )
    assert status == "exceeded" and diff == Decimal("200.00")


def test_items_immutability_from_budget_limit() -> None:
    """Проверка неизменности состава и объёма позиций плана при любом лимите бюджета."""
    item1 = _item(sku="SKU-1", quantity=Decimal("5.000"), total_cost=Decimal("500.00"))
    item2 = _item(sku="SKU-2", quantity=Decimal("15.000"), total_cost=Decimal("1500.00"))
    items = [item1, item2]

    # Сравнение при разных лимитах: None, большой, малый, нулевой
    for limit in [None, Decimal("5000.00"), Decimal("1000.00"), Decimal("0.00")]:
        budget = build_procurement_plan_breakdowns(
            items=items,
            as_of=date(2026, 9, 15),
            horizon_months=1,
            budget_limit=limit,
        )
        assert len(items) == 2
        assert items[0].quantity == Decimal("5.000")
        assert items[1].quantity == Decimal("15.000")
        assert budget.known_total == Decimal("2000.00")
        assert budget.total_quantity == Decimal("20.000")


def test_explanation_structure_and_completeness() -> None:
    """Проверка структуры объяснения: исходные данные, правила (формулы) и допущения."""
    item1 = _item(
        sku="SKU-1",
        quantity=Decimal("10.000"),
        unit_price=Decimal("50.00"),
        total_cost=Decimal("500.00"),
    )
    budget = build_procurement_plan_breakdowns(
        items=[item1],
        as_of=date(2026, 9, 15),
        horizon_months=3,
        budget_limit=Decimal("1000.00"),
    )

    explanation = build_plan_explanation(
        as_of=date(2026, 9, 15),
        horizon_months=3,
        service_days=7,
        budget_limit=Decimal("1000.00"),
        horizon_start=date(2026, 9, 16),
        horizon_end=date(2026, 12, 15),
        items=[item1],
        budget=budget,
    )

    # Проверка исходных данных data_used
    data_dict = {item.name: item for item in explanation.data_used}
    assert data_dict["as_of"].value == "2026-09-15"
    assert data_dict["horizon_months"].value == 3
    assert data_dict["service_days"].value == 7
    assert data_dict["horizon_dates"].value == "2026-09-16 .. 2026-12-15"
    assert data_dict["budget_limit"].value == "1000.00"
    assert data_dict["known_total_cost"].value == "500.00"
    assert data_dict["total_items_count"].value == 1
    assert data_dict["is_price_complete"].value is True
    assert data_dict["limit_status"].value == "within"
    assert data_dict["limit_difference"].value == "-500.00"

    # Проверка применённых правил и формул (FEFO, страховой запас, плечо, кванты)
    formulas_text = " ".join(explanation.formulas)
    assert "FEFO" in formulas_text
    assert "safety_stock" in formulas_text
    assert "lead_time_days" in formulas_text
    assert "min_order_qty" in formulas_text or "упаковок" in formulas_text
    assert "total_cost" in formulas_text
    assert "limit_difference" in formulas_text

    # Проверка допущений
    assumptions_text = " ".join(explanation.assumptions)
    assert "Лимит бюджета носит информационный характер" in assumptions_text
    assert "within" in assumptions_text


def test_incompleteness_reasons_readability() -> None:
    """Проверка читаемости и полноты причин неполноты исходных данных."""
    unpriced_item = _item(
        sku="SKU-UNPRICED",
        unit_price=None,
        total_cost=None,
        warnings=[WARN_PRICE_UNKNOWN],
    )
    undated_item = _item(
        sku="SKU-UNDATED",
        order_date=None,
        unit_price=Decimal("100.00"),
        total_cost=Decimal("200.00"),
        warnings=[WARN_LEAD_TIME_UNKNOWN],
    )
    deficit_item = _item(sku="SKU-DEFICIT", warnings=[WARN_TEMPORARY_DEFICIT])
    delayed_item = _item(sku="SKU-DELAYED", warnings=[WARN_ORDER_DELAYED])

    items = [unpriced_item, undated_item, deficit_item, delayed_item]
    general_warnings = [WARN_INCOMPLETE_HISTORY, WARN_DELIVERY_BEYOND_HORIZON]

    budget = build_procurement_plan_breakdowns(
        items=items,
        as_of=date(2026, 9, 15),
        horizon_months=1,
        budget_limit=Decimal("5000.00"),
    )
    assert budget.limit_status == "undetermined"

    reasons = get_incompleteness_reasons(
        items=items,
        budget=budget,
        warnings=general_warnings,
    )
    all_reasons_text = " ".join(reasons)

    assert "Отсутствие цен" in all_reasons_text
    assert "null" in all_reasons_text
    assert "Неизвестное плечо поставки" in all_reasons_text
    assert "Неполная история расхода" in all_reasons_text
    assert "Временный дефицит" in all_reasons_text
    assert "Задержанные заказы" in all_reasons_text
    assert "Поставка за горизонтом" in all_reasons_text
    assert "undetermined" in all_reasons_text

    explanation = build_plan_explanation(
        as_of=date(2026, 9, 15),
        horizon_months=1,
        budget_limit=Decimal("5000.00"),
        items=items,
        budget=budget,
        warnings=general_warnings,
    )
    assert len(explanation.incompleteness_reasons) == len(reasons)
    for reason in reasons:
        assert reason in explanation.assumptions


def test_complete_data_has_no_incompleteness_reasons() -> None:
    """Проверка, что при полных данных список причин неполноты пуст."""
    item = _item(sku="SKU-OK", unit_price=Decimal("10.00"), total_cost=Decimal("100.00"))
    budget = build_procurement_plan_breakdowns(
        items=[item],
        as_of=date(2026, 9, 15),
        horizon_months=1,
        budget_limit=Decimal("500.00"),
    )
    assert budget.limit_status == "within"
    assert budget.is_price_complete is True
    assert budget.is_dates_complete is True

    reasons = get_incompleteness_reasons(items=[item], budget=budget)
    assert reasons == []

    explanation = build_plan_explanation(
        as_of=date(2026, 9, 15),
        horizon_months=1,
        budget_limit=Decimal("500.00"),
        items=[item],
        budget=budget,
    )
    assert explanation.incompleteness_reasons == []
