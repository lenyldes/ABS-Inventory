"""Шаблоны формул и допущений для объяснения прогноза."""

from decimal import Decimal

from app.forecasting.domain import (
    ConsumptionMetrics,
    DailyFefoResult,
    OrderRecommendation,
    ProcurementContext,
)


def build_explanation_formulas(
    procurement_context: ProcurementContext,
    order_rec: OrderRecommendation,
) -> list[str]:
    """Формирует список формул, применённых в расчёте потребности."""
    formulas: list[str] = [
        "Чистый расход за 90 дней: total_consumption_90d = "
        "sum(max(0, расход - связанные возвраты) по списаниям 90-дневного окна)",
        "Среднесуточный расход: a = total_consumption_90d / 90",
        "Прогноз расхода на горизонт: forecast_consumption = round(a * days_count, 3)",
        "Страховой запас: safety_stock = round(a * service_days, 3)",
    ]
    if procurement_context.lead_time_days is not None:
        formulas.append(
            "Точка перезаказа: reorder_point = round(a * (lead_time_days + service_days), 3)"
        )
    else:
        formulas.append("Точка перезаказа: не рассчитывается, так как срок поставки не указан")

    formulas.append(
        "Потребность к закупке: P_need = "
        "(forecast_consumption + safety_stock) - (available_stock + incoming_qty - expired_qty)"
    )

    if (
        procurement_context.min_order_qty is not None
        and procurement_context.min_order_qty > Decimal("0.000")
    ):
        formulas.append("Учёт минимального объёма: P_eff = max(P_need, min_order_qty)")

    if procurement_context.package_size is not None and procurement_context.package_size > Decimal(
        "0.000"
    ):
        formulas.append(
            "Кратность упаковке: recommended_qty = ceil(P_eff / package_size) * package_size"
        )
    else:
        formulas.append("Рекомендуемый объём: recommended_qty = max(0, P_need)")

    if order_rec.unit_price is not None:
        formulas.append(
            "Оценочная стоимость заказа: total_cost = round(recommended_qty * unit_price, 2)"
        )

    return formulas


def build_explanation_assumptions(
    service_days: int,
    consumption_metrics: ConsumptionMetrics,
    procurement_context: ProcurementContext,
) -> list[str]:
    """Формирует список допущений и ограничений расчёта."""
    assumptions: list[str] = [
        (
            "Посуточный расход моделируется по алгоритму FEFO "
            "(в первую очередь списываются партии с наиболее ранним сроком годности)."
        ),
        (
            "Среднесуточный расход округляется до 6 знаков, количества — до 3 знаков, "
            "цена и стоимость — до 2 знаков по правилу ROUND_HALF_UP."
        ),
    ]

    if procurement_context.pending_orders:
        assumptions.append(
            "Ожидаемые будущие поставки принимаются годными на всём горизонте прогноза."
        )

    if procurement_context.price_source == "estimated":
        assumptions.append(
            "Для расчёта стоимости использована ориентировочная цена из условий поставщика "
            "из-за отсутствия фактических поступлений."
        )
    elif procurement_context.price_source == "receipt":
        assumptions.append(
            "Для расчёта стоимости использована фактическая цена последней закупки "
            "у основного поставщика."
        )
    elif procurement_context.unit_price is None:
        assumptions.append("Цена товара не указана; расчёт оценочной стоимости закупки невозможен.")

    if procurement_context.lead_time_days is None:
        assumptions.append(
            "Срок поставки не задан в условиях поставщика; дата и точка заказа не определены."
        )

    if not consumption_metrics.is_history_complete:
        assumptions.append(
            f"История движений ({consumption_metrics.history_days} дн.) составляет менее 90 дней; "
            "среднесуточный расход рассчитан по имеющимся данным "
            "с фиксированным знаменателем 90 дней."
        )

    if procurement_context.delayed_orders:
        del_count = len(procurement_context.delayed_orders)
        assumptions.append(
            f"Задержанные заказы со сроком поступления не позже as_of ({del_count} шт.) "
            "исключены из расчёта будущих поступлений."
        )

    if service_days == 0:
        assumptions.append("Страховой запас не формируется (service_days = 0).")

    return assumptions


def build_forecast_warnings(
    order_rec: OrderRecommendation,
    consumption_metrics: ConsumptionMetrics,
    daily_fefo: DailyFefoResult,
    procurement_context: ProcurementContext,
) -> list[str]:
    """Формирует объединённый список предупреждений расчёта."""
    warnings: list[str] = list(order_rec.warnings)

    if not consumption_metrics.is_history_complete:
        warn_history = f"История движений неполная ({consumption_metrics.history_days} дн. из 90)"
        if warn_history not in warnings:
            warnings.append(warn_history)

    if procurement_context.delayed_orders:
        del_cnt = len(procurement_context.delayed_orders)
        warn_delayed = (
            f"Имеются задержанные заказы поставщикам ({del_cnt} шт.) "
            "со сроком поставки до или в день расчёта"
        )
        if warn_delayed not in warnings:
            warnings.append(warn_delayed)

    if daily_fefo.has_temporary_stockout:
        warn_gap = "Возникает временный дефицит запаса до поступления ожидаемого заказа"
        if warn_gap not in warnings:
            warnings.append(warn_gap)

    if daily_fefo.total_expired > Decimal("0.000"):
        warn_exp = (
            f"На горизонте прогноза ожидается списание по сроку годности: "
            f"{daily_fefo.total_expired} ед."
        )
        if warn_exp not in warnings:
            warnings.append(warn_exp)

    return warnings
