"""Формирование структурированного объяснения плана закупок и агрегированных данных."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from app.api.plan_breakdown_schemas import PlanBudgetSchema
from app.api.plan_schemas import (
    ExplanationItemSchema,
    PlanExplanationSchema,
    PlanItemSchema,
)
from app.procurement.rounding import ZERO_PRICE
from app.procurement_plan.explanation_templates import (
    build_plan_explanation_assumptions,
    build_plan_explanation_formulas,
    get_incompleteness_reasons,
)


def build_plan_explanation_data_used(
    as_of: date,
    horizon_months: int,
    service_days: int = 0,
    horizon_start: date | None = None,
    horizon_end: date | None = None,
    budget_limit: Decimal | None = None,
    items: Sequence[PlanItemSchema] = (),
    budget: PlanBudgetSchema | None = None,
    existing_orders_count: int = 0,
) -> list[ExplanationItemSchema]:
    """Формирует структурированный список исходных данных и агрегированных параметров."""
    known_total = budget.known_total if budget is not None else ZERO_PRICE
    is_price_complete = budget.is_price_complete if budget is not None else True
    is_dates_complete = budget.is_dates_complete if budget is not None else True
    undated_count = (
        budget.undated_count if budget is not None else sum(1 for it in items if it.is_undated)
    )
    unpriced_count = (
        budget.unknown_price_count
        if budget is not None
        else sum(1 for it in items if it.total_cost is None)
    )
    limit_status = budget.limit_status if budget is not None else None
    limit_difference = budget.limit_difference if budget is not None else None

    data_used: list[ExplanationItemSchema] = [
        ExplanationItemSchema(
            name="as_of",
            value=as_of.isoformat(),
            source="Параметр запроса: контрольная дата актуальности расчёта",
        ),
        ExplanationItemSchema(
            name="horizon_months",
            value=horizon_months,
            source="Параметр запроса: горизонт планирования потребности в месяцах",
        ),
        ExplanationItemSchema(
            name="service_days",
            value=service_days,
            source="Параметр запроса: количество дней целевого страхового запаса",
        ),
    ]

    if horizon_start and horizon_end:
        data_used.append(
            ExplanationItemSchema(
                name="horizon_dates",
                value=f"{horizon_start.isoformat()} .. {horizon_end.isoformat()}",
                source="Расчёт: календарный интервал скользящего горизонта потребности",
            )
        )

    if budget_limit is not None:
        data_used.append(
            ExplanationItemSchema(
                name="budget_limit",
                value=str(budget_limit),
                source="Параметр запроса: информационный лимит бюджета в рублях",
            )
        )

    data_used.extend(
        [
            ExplanationItemSchema(
                name="known_total_cost",
                value=str(known_total),
                source="Расчёт: суммарная известная стоимость рекомендуемых заказов плана",
            ),
            ExplanationItemSchema(
                name="total_items_count",
                value=len(items),
                source="Расчёт: общее количество сформированных позиций плана",
            ),
            ExplanationItemSchema(
                name="dated_items_count",
                value=len([it for it in items if not it.is_undated]),
                source="Расчёт: количество позиций с известным сроком и календарной датой заказа",
            ),
            ExplanationItemSchema(
                name="undated_items_count",
                value=undated_count,
                source="Расчёт: количество недатированных позиций (срок поставщика не задан)",
            ),
            ExplanationItemSchema(
                name="unpriced_items_count",
                value=unpriced_count,
                source="Расчёт: количество позиций с отсутствующей ценой закупки",
            ),
            ExplanationItemSchema(
                name="existing_orders_count",
                value=existing_orders_count,
                source=(
                    "БД: количество оформленных неполученных заказов, учтённых как входные поставки"
                ),
            ),
            ExplanationItemSchema(
                name="is_price_complete",
                value=is_price_complete,
                source="Расчёт: признак полноты стоимостной оценки всех позиций плана",
            ),
            ExplanationItemSchema(
                name="is_dates_complete",
                value=is_dates_complete,
                source="Расчёт: признак полноты календарного распределения по месяцам",
            ),
        ]
    )

    if limit_status is not None:
        data_used.append(
            ExplanationItemSchema(
                name="limit_status",
                value=limit_status,
                source=(
                    "Расчёт: статус соблюдения лимита бюджета (within, exceeded, undetermined)"
                ),
            )
        )

    if limit_difference is not None:
        data_used.append(
            ExplanationItemSchema(
                name="limit_difference",
                value=str(limit_difference),
                source=(
                    "Расчёт: разница известной стоимости и лимита бюджета "
                    "(known_total - budget_limit)"
                ),
            )
        )

    return data_used


def build_plan_explanation(
    as_of: date,
    horizon_months: int,
    service_days: int = 0,
    horizon_start: date | None = None,
    horizon_end: date | None = None,
    budget_limit: Decimal | None = None,
    items: Sequence[PlanItemSchema] = (),
    budget: PlanBudgetSchema | None = None,
    existing_orders: Sequence[Any] = (),
    warnings: Sequence[str] = (),
) -> PlanExplanationSchema:
    """Формирует структурированное объяснение плана, правил, допущений и причин неполноты."""
    eff_budget_limit = (
        budget_limit
        if budget_limit is not None
        else (budget.budget_limit if budget is not None else None)
    )
    data_used = build_plan_explanation_data_used(
        as_of=as_of,
        horizon_months=horizon_months,
        service_days=service_days,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        budget_limit=eff_budget_limit,
        items=items,
        budget=budget,
        existing_orders_count=len(existing_orders),
    )
    formulas = build_plan_explanation_formulas()
    assumptions = build_plan_explanation_assumptions(
        budget=budget,
        items=items,
        warnings=warnings,
    )
    incompleteness_reasons = get_incompleteness_reasons(
        items=items,
        budget=budget,
        warnings=warnings,
    )

    return PlanExplanationSchema(
        data_used=data_used,
        formulas=formulas,
        assumptions=assumptions,
        incompleteness_reasons=incompleteness_reasons,
    )


__all__ = [
    "build_plan_explanation",
    "build_plan_explanation_assumptions",
    "build_plan_explanation_data_used",
    "build_plan_explanation_formulas",
    "get_incompleteness_reasons",
]
