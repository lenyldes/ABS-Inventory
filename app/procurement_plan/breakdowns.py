"""Агрегация календарных и предметных аналитических разрезов бюджета плана закупок."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.api.plan_breakdown_schemas import (
    PlanBudgetSchema,
    PlanCategoryBreakdownItem,
    PlanLocationBreakdownItem,
    PlanMonthlyBreakdownItem,
    PlanSkuBreakdownItem,
    PlanUndatedBreakdownItem,
)
from app.api.plan_schemas import PlanItemSchema
from app.forecasting.domain import compute_horizon_dates
from app.procurement.rounding import (
    PRICE_QUANT,
    QTY_QUANT,
    ZERO_PRICE,
    ZERO_QTY,
)
from app.procurement_plan.dates import generate_horizon_months
from app.procurement_plan.entity_breakdowns import (
    build_category_breakdown,
    build_location_breakdown,
    build_sku_breakdown,
)


def evaluate_budget_limit(
    known_total: Decimal,
    budget_limit: Decimal | None,
    is_price_complete: bool,
) -> tuple[str | None, Decimal | None]:
    """Сравнивает известную сумму бюджета с лимитом.

    Возвращает (limit_status, limit_difference).
    - limit_difference = (known_total - budget_limit).quantize(PRICE_QUANT)
    - exceeded: если known_total > budget_limit
    - within: если known_total <= budget_limit и все стоимости известны
    - undetermined: если known_total <= budget_limit, но хотя бы одна стоимость не известна
    """
    if budget_limit is None:
        return None, None
    diff = (known_total - budget_limit).quantize(PRICE_QUANT)
    if known_total > budget_limit:
        return "exceeded", diff
    if is_price_complete:
        return "within", diff
    return "undetermined", diff


def build_monthly_breakdown(
    items: Sequence[PlanItemSchema],
    horizon_months_info: Sequence[tuple[str, int, int, bool]] | None = None,
) -> list[PlanMonthlyBreakdownItem]:
    """Строит помесячный календарный разрез бюджета по дате заказа."""
    dated_items = [it for it in items if it.order_date is not None]
    items_by_month: dict[str, list[PlanItemSchema]] = defaultdict(list)
    for it in dated_items:
        assert it.order_date is not None
        m_key = it.order_date.strftime("%Y-%m")
        items_by_month[m_key].append(it)

    month_meta: dict[str, tuple[int, int, bool]] = {}
    if horizon_months_info:
        for m_key, yr, m_num, is_part in horizon_months_info:
            month_meta[m_key] = (yr, m_num, is_part)

    for m_key in items_by_month:
        if m_key not in month_meta:
            yr = int(m_key[:4])
            m_num = int(m_key[5:7])
            month_meta[m_key] = (yr, m_num, False)

    all_month_keys = sorted(month_meta.keys())
    result: list[PlanMonthlyBreakdownItem] = []

    for m_key in all_month_keys:
        yr, m_num, is_part = month_meta[m_key]
        m_items = items_by_month.get(m_key, [])
        items_count = len(m_items)
        total_qty = sum((it.quantity for it in m_items), ZERO_QTY).quantize(
            QTY_QUANT, rounding=ROUND_HALF_UP
        )
        known_total = sum(
            (it.total_cost for it in m_items if it.total_cost is not None),
            ZERO_PRICE,
        ).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)
        unpriced_count = sum(1 for it in m_items if it.total_cost is None)
        is_price_complete = unpriced_count == 0
        has_unpriced = unpriced_count > 0

        result.append(
            PlanMonthlyBreakdownItem(
                month=m_key,
                year=yr,
                month_number=m_num,
                known_total=known_total,
                total_cost=known_total,
                total_quantity=total_qty,
                items_count=items_count,
                unknown_price_count=unpriced_count,
                unpriced_items_count=unpriced_count,
                is_price_complete=is_price_complete,
                has_unpriced_items=has_unpriced,
                is_partial=is_part,
            )
        )

    return result


def build_undated_breakdown(items: Sequence[PlanItemSchema]) -> PlanUndatedBreakdownItem:
    """Строит агрегат недатированных позиций плана закупок."""
    undated_items = [it for it in items if it.order_date is None]
    items_count = len(undated_items)
    total_qty = sum((it.quantity for it in undated_items), ZERO_QTY).quantize(
        QTY_QUANT, rounding=ROUND_HALF_UP
    )
    known_total = sum(
        (it.total_cost for it in undated_items if it.total_cost is not None),
        ZERO_PRICE,
    ).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)
    unpriced_count = sum(1 for it in undated_items if it.total_cost is None)
    is_price_complete = unpriced_count == 0
    has_unpriced = unpriced_count > 0

    return PlanUndatedBreakdownItem(
        known_total=known_total,
        total_cost=known_total,
        total_quantity=total_qty,
        items_count=items_count,
        unknown_price_count=unpriced_count,
        unpriced_items_count=unpriced_count,
        is_price_complete=is_price_complete,
        has_unpriced_items=has_unpriced,
    )


def build_procurement_plan_breakdowns(
    items: Sequence[PlanItemSchema],
    as_of: date | None = None,
    horizon_months: int | None = None,
    horizon_end: date | None = None,
    sku_names: dict[str, str] | None = None,
    sku_categories: dict[str, str] | None = None,
    location_names: dict[str, str] | None = None,
    budget_limit: Decimal | None = None,
    include_empty_months: bool = True,
) -> PlanBudgetSchema:
    """Агрегирует календарные и предметные разрезы бюджета из списка позиций плана."""
    dated_items = [it for it in items if it.order_date is not None]
    undated_items = [it for it in items if it.order_date is None]

    known_total = sum(
        (it.total_cost for it in items if it.total_cost is not None),
        ZERO_PRICE,
    ).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)
    total_quantity = sum(
        (it.quantity for it in items),
        ZERO_QTY,
    ).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)

    unknown_price_count = sum(1 for it in items if it.total_cost is None)
    is_price_complete = unknown_price_count == 0
    has_unpriced_items = unknown_price_count > 0
    undated_count = len(undated_items)
    is_dates_complete = undated_count == 0

    horizon_months_info: list[tuple[str, int, int, bool]] | None = None
    if as_of is not None and include_empty_months:
        if horizon_end is None and horizon_months is not None:
            _, horizon_end, _ = compute_horizon_dates(as_of=as_of, horizon_months=horizon_months)
        if horizon_end is not None:
            horizon_months_info = generate_horizon_months(as_of=as_of, horizon_end=horizon_end)

    by_month = build_monthly_breakdown(dated_items, horizon_months_info=horizon_months_info)
    undated = build_undated_breakdown(undated_items)
    by_sku = build_sku_breakdown(items, sku_names=sku_names, sku_categories=sku_categories)
    by_category = build_category_breakdown(items)
    by_location = build_location_breakdown(items, location_names=location_names)

    limit_status, limit_difference = evaluate_budget_limit(
        known_total=known_total,
        budget_limit=budget_limit,
        is_price_complete=is_price_complete,
    )

    return PlanBudgetSchema(
        known_total=known_total,
        total_cost=known_total,
        total_quantity=total_quantity,
        is_price_complete=is_price_complete,
        is_dates_complete=is_dates_complete,
        unknown_price_count=unknown_price_count,
        unpriced_items_count=unknown_price_count,
        has_unpriced_items=has_unpriced_items,
        undated_count=undated_count,
        by_month=by_month,
        undated=undated,
        by_sku=by_sku,
        by_category=by_category,
        by_location=by_location,
        budget_limit=budget_limit,
        limit_status=limit_status,
        limit_difference=limit_difference,
    )


__all__ = [
    "PlanBudgetSchema",
    "PlanCategoryBreakdownItem",
    "PlanLocationBreakdownItem",
    "PlanMonthlyBreakdownItem",
    "PlanSkuBreakdownItem",
    "PlanUndatedBreakdownItem",
    "build_category_breakdown",
    "build_location_breakdown",
    "build_monthly_breakdown",
    "build_procurement_plan_breakdowns",
    "build_sku_breakdown",
    "build_undated_breakdown",
    "evaluate_budget_limit",
]
