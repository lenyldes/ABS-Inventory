"""Шаблоны формул, правил, допущений и причин неполноты для объяснения плана закупок."""

from collections.abc import Sequence

from app.api.plan_breakdown_schemas import PlanBudgetSchema
from app.api.plan_schemas import PlanItemSchema
from app.procurement_plan.warnings import (
    WARN_DELIVERY_BEYOND_HORIZON,
    WARN_INCOMPLETE_HISTORY,
    WARN_ORDER_DELAYED,
    WARN_TEMPORARY_DEFICIT,
)


def get_incompleteness_reasons(
    items: Sequence[PlanItemSchema] = (),
    budget: PlanBudgetSchema | None = None,
    warnings: Sequence[str] = (),
) -> list[str]:
    """Формирует список читаемых причин неполноты исходных данных и расчёта."""
    reasons: list[str] = []

    unpriced_count = (
        budget.unknown_price_count
        if budget is not None
        else sum(1 for it in items if it.total_cost is None)
    )
    if unpriced_count > 0:
        reasons.append(
            f"Отсутствие цен: у {unpriced_count} позиций не определена цена закупки "
            "(нет фактических поступлений и ориентировочной цены поставщика); "
            "количество и даты сохранены, а unit_price и total_cost не определены (null)."
        )

    undated_count = (
        budget.undated_count if budget is not None else sum(1 for it in items if it.is_undated)
    )
    if undated_count > 0:
        reasons.append(
            f"Неизвестное плечо поставки: для {undated_count} позиций не указан срок "
            "поставки в условиях поставщика; сформирована недатированная оценка потребности "
            "на весь горизонт без привязки к календарному месяцу."
        )

    has_incomplete_history = any(
        WARN_INCOMPLETE_HISTORY in w or "История движений неполная" in w
        for it in items
        for w in it.warnings
    ) or any(WARN_INCOMPLETE_HISTORY in w or "История движений неполная" in w for w in warnings)
    if has_incomplete_history:
        reasons.append(
            "Неполная история расхода: для части товаров история движений составляет "
            "менее 90 дней; среднесуточный расход рассчитан по имеющимся данным "
            "с фиксированным знаменателем 90 дней."
        )

    has_temporary_deficit = any(
        WARN_TEMPORARY_DEFICIT in w or "дефицит" in w for it in items for w in it.warnings
    ) or any(WARN_TEMPORARY_DEFICIT in w or "дефицит" in w for w in warnings)
    if has_temporary_deficit:
        reasons.append(
            "Временный дефицит: потребность возникает до даты ближайшего возможного "
            "поступления заказа; дни до прибытия поставки остаются дефицитом."
        )

    has_delayed_orders = any(
        WARN_ORDER_DELAYED in w or "задержан" in w for it in items for w in it.warnings
    ) or any(WARN_ORDER_DELAYED in w or "задержан" in w for w in warnings)
    if has_delayed_orders:
        reasons.append(
            "Задержанные заказы: зафиксированы оформленные ранее заказы поставщикам "
            "с датой поступления не позже as_of; они исключены из расчёта покрытия "
            "до переноса даты или фактической приёмки."
        )

    has_beyond_horizon = any(
        WARN_DELIVERY_BEYOND_HORIZON in w or "за горизонтом" in w
        for it in items
        for w in it.warnings
    ) or any(WARN_DELIVERY_BEYOND_HORIZON in w or "за горизонтом" in w for w in warnings)
    if has_beyond_horizon:
        reasons.append(
            "Поставка за горизонтом: ближайшая возможная поставка выходит за границы "
            "горизонта; позиция не создаётся, потребность остаётся необеспеченной."
        )

    if budget is not None and budget.limit_status == "undetermined":
        reasons.append(
            "Статус лимита бюджета не определён (undetermined): известная сумма плана "
            "не превышает лимит, однако из-за позиций с неполной ценой итоговые затраты "
            "могут превысить установленный лимит."
        )

    return reasons


def build_plan_explanation_formulas() -> list[str]:
    """Формирует список формул и правил, применённых при расчёте плана."""
    return [
        (
            "FEFO (First Expired, First Out): посуточное списание партий с наиболее "
            "ранним сроком годности в первую очередь."
        ),
        (
            "Страховой запас: целевой буфер запаса safety_stock = "
            "round(average_daily_consumption * service_days, 3)."
        ),
        (
            "Плечо поставки: планируемая дата поступления = "
            "дата заказа + lead_time_days календарных дней."
        ),
        (
            "Месячная цель пополнения: объём заказа покрывает потребность от даты "
            "поступления до min(дата поступления + 1 календарный месяц, конец горизонта) "
            "и целевой страховой запас."
        ),
        (
            "Кванты поставки: объём заказа округляется вверх до min_order_qty "
            "и целого числа упаковок (package_size)."
        ),
        (
            "Оценочная стоимость позиции: total_cost = round(quantity * unit_price, 2) "
            "на дату as_of по действующим условиям поставщика."
        ),
        (
            "Сравнение с лимитом бюджета: limit_difference = known_total - budget_limit "
            "(информационное сравнение без обрезания и фильтрации состава позиций)."
        ),
    ]


def build_plan_explanation_assumptions(
    budget: PlanBudgetSchema | None = None,
    items: Sequence[PlanItemSchema] = (),
    warnings: Sequence[str] = (),
) -> list[str]:
    """Формирует допущения расчёта, включая причины неполноты и пояснение лимита."""
    assumptions: list[str] = [
        (
            "Потребность рассчитывается на скользящий горизонт на основе "
            "90-дневной истории расхода на дату as_of."
        ),
        ("Ожидаемые и виртуальные поставки принимаются годными на всём горизонте планирования."),
        (
            "Лимит бюджета носит информационный характер: состав и объём рекомендаций "
            "не обрезаются и не изменяются при превышении лимита."
        ),
        ("Закупочные цены фиксируются на дату as_of; будущее изменение цен не моделируется."),
        (
            "Оформленные ранее заказы поставщикам учитываются как входные поставки "
            "и исключены из стоимости новых рекомендаций."
        ),
    ]

    reasons = get_incompleteness_reasons(items=items, budget=budget, warnings=warnings)
    assumptions.extend(reasons)

    if budget is not None and budget.budget_limit is not None:
        if budget.limit_status == "exceeded":
            assumptions.append(
                f"Лимит бюджета превышен (exceeded): известная стоимость плана "
                f"({budget.known_total} руб.) превышает лимит ({budget.budget_limit} руб.) "
                f"на {budget.limit_difference} руб."
            )
        elif budget.limit_status == "within":
            assumptions.append(
                f"План укладывается в бюджет (within): известная стоимость плана "
                f"({budget.known_total} руб.) не превышает лимит ({budget.budget_limit} руб.), "
                "все цены позиций полностью определены."
            )

    return assumptions


__all__ = [
    "build_plan_explanation_assumptions",
    "build_plan_explanation_formulas",
    "get_incompleteness_reasons",
]
