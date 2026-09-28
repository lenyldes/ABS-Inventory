"""Формирование структурированного объяснения прогноза и списка предупреждений."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from app.forecasting.domain import (
    ConsumptionMetrics,
    DailyFefoResult,
    ExplanationItem,
    ForecastExplanation,
    OrderRecommendation,
    ProcurementContext,
)
from app.forecasting.explanation_templates import (
    build_explanation_assumptions,
    build_explanation_formulas,
    build_forecast_warnings,
)
from app.inventory.domain import MovementSnapshot, StockBalance


def _consumption_sources(
    movements: Sequence[MovementSnapshot], as_of: date
) -> tuple[Decimal, list[ExplanationItem]]:
    """Находит исходный расход и связанные возвраты, учтённые за 90 дней."""
    window_start = as_of - timedelta(days=89)
    consumes = {
        movement.id: movement
        for movement in movements
        if movement.status == "active"
        and movement.type == "consume"
        and movement.id is not None
        and window_start <= movement.operation_date <= as_of
    }
    gross_consumption = sum((movement.quantity for movement in consumes.values()), Decimal("0.000"))
    returns = [
        movement
        for movement in movements
        if movement.status == "active"
        and movement.type == "return"
        and movement.operation_date <= as_of
        and movement.parent_movement_id in consumes
    ]
    return_items = [
        ExplanationItem(
            name=f"linked_return_{movement.id}",
            value=str(movement.quantity),
            source=(
                f"Журнал движений: возврат {movement.doc_number} (id={movement.id}) "
                f"к расходу {consumes[movement.parent_movement_id].doc_number} "
                f"(id={movement.parent_movement_id})"
            ),
        )
        for movement in returns
    ]
    return gross_consumption, return_items


def build_forecast_explanation(
    as_of: date,
    days_count: int,
    service_days: int,
    balance: StockBalance,
    consumption_metrics: ConsumptionMetrics,
    movements: Sequence[MovementSnapshot],
    daily_fefo: DailyFefoResult,
    procurement_context: ProcurementContext,
    order_rec: OrderRecommendation,
) -> tuple[ForecastExplanation, list[str]]:
    """Формирует структурированное объяснение прогноза и предупреждения.

    Включает data_used, formulas и assumptions.
    """
    gross_consumption, return_items = _consumption_sources(movements, as_of)
    returned_qty = sum((Decimal(item.value) for item in return_items), Decimal("0.000"))
    data_used: list[ExplanationItem] = [
        ExplanationItem(
            name="gross_consumption_90d",
            value=str(gross_consumption),
            source="Журнал движений: активные списания за 90 календарных дней до as_of",
        ),
        ExplanationItem(
            name="linked_returns_90d",
            value=str(returned_qty),
            source="Журнал движений: активные возвраты к списаниям 90-дневного окна на as_of",
        ),
        ExplanationItem(
            name="total_consumption_90d",
            value=str(consumption_metrics.total_consumption_90d),
            source="Расчёт: исходный расход за 90 дней за вычетом связанных возвратов",
        ),
        ExplanationItem(
            name="average_daily_consumption",
            value=str(consumption_metrics.average_daily_consumption),
            source="Расчёт: total_consumption_90d / 90",
        ),
        ExplanationItem(
            name="history_days",
            value=consumption_metrics.history_days,
            source="Количество календарных дней от первого движения до as_of",
        ),
        ExplanationItem(
            name="horizon_days",
            value=days_count,
            source="Параметры запроса прогноза",
        ),
        ExplanationItem(
            name="service_days",
            value=service_days,
            source="Параметры запроса прогноза",
        ),
        ExplanationItem(
            name="current_stock",
            value=str(balance.current_stock),
            source="Складской учётный остаток на контрольную дату as_of",
        ),
        ExplanationItem(
            name="available_stock",
            value=str(balance.available_stock),
            source="Годный остаток склада без учёта просроченных партий",
        ),
    ]
    data_used.extend(return_items)

    for b in balance.batches:
        if b.available_quantity > Decimal("0.000"):
            exp_text = b.expiry_date.isoformat() if b.expiry_date else "бессрочно"
            data_used.append(
                ExplanationItem(
                    name=f"batch_{b.batch_number}",
                    value=str(b.available_quantity),
                    source=(
                        f"Партия id={b.batch_id}, поступление {b.receipt_date.isoformat()}, "
                        f"годен до {exp_text}"
                    ),
                )
            )

    total_incoming = sum(
        (o.pending_qty for o in procurement_context.pending_orders),
        Decimal("0.000"),
    ).quantize(Decimal("0.001"))
    data_used.append(
        ExplanationItem(
            name="incoming_qty",
            value=str(total_incoming),
            source="Сумма неполученных заказов со сроком поступления позже as_of",
        )
    )
    for o in procurement_context.pending_orders:
        data_used.append(
            ExplanationItem(
                name=f"pending_order_{o.doc_number}",
                value=str(o.pending_qty),
                source=f"Заказ id={o.order_id}, ожидаемая дата {o.expected_date.isoformat()}",
            )
        )

    supp_title = procurement_context.supplier_name or procurement_context.supplier_id
    data_used.append(
        ExplanationItem(
            name="lead_time_days",
            value=procurement_context.lead_time_days,
            source=(
                f"Условия поставщика ({supp_title})"
                if procurement_context.lead_time_days is not None
                else "Срок поставки не указан"
            ),
        )
    )
    data_used.append(
        ExplanationItem(
            name="min_order_qty",
            value=str(procurement_context.min_order_qty)
            if procurement_context.min_order_qty is not None
            else None,
            source="Условия поставщика: минимальная партия заказа"
            if procurement_context.min_order_qty is not None
            else "Минимальная партия не задана",
        )
    )
    data_used.append(
        ExplanationItem(
            name="package_size",
            value=str(procurement_context.package_size)
            if procurement_context.package_size is not None
            else None,
            source="Условия поставщика: размер упаковки"
            if procurement_context.package_size is not None
            else "Размер упаковки не задан",
        )
    )

    if procurement_context.price_source == "receipt":
        price_src = "Фактическая цена последнего поступления от поставщика"
    elif procurement_context.price_source == "estimated":
        price_src = "Ориентировочная цена из условий поставщика"
    else:
        price_src = "Цена не указана"

    data_used.append(
        ExplanationItem(
            name="unit_price",
            value=str(procurement_context.unit_price)
            if procurement_context.unit_price is not None
            else None,
            source=price_src,
        )
    )

    formulas = build_explanation_formulas(procurement_context, order_rec)
    assumptions = build_explanation_assumptions(
        service_days, consumption_metrics, procurement_context
    )
    warnings = build_forecast_warnings(
        order_rec, consumption_metrics, daily_fefo, procurement_context
    )

    explanation = ForecastExplanation(
        data_used=tuple(data_used),
        formulas=tuple(formulas),
        assumptions=tuple(assumptions),
    )

    return explanation, warnings
