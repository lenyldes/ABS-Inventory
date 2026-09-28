"""Чистые функции расчёта точки и даты заказа, рекомендуемого объёма и стоимости."""

from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from app.forecasting.domain import DailyFefoResult, OrderRecommendation

_ZERO_QTY = Decimal("0.000")
_ZERO_PRICE = Decimal("0.00")
_QTY_QUANT = Decimal("0.001")
_PRICE_QUANT = Decimal("0.01")


def calculate_order_recommendation(
    as_of: date,
    average_daily_consumption: Decimal,
    days_count: int,
    service_days: int = 0,
    lead_time_days: int | None = None,
    package_size: Decimal | None = None,
    min_order_qty: Decimal | None = None,
    unit_price: Decimal | None = None,
    available_stock: Decimal = _ZERO_QTY,
    daily_fefo: DailyFefoResult | None = None,
    incoming_qty: Decimal = _ZERO_QTY,
) -> OrderRecommendation:
    """Рассчитывает потребность, точку и дату заказа, объём закупки и стоимость."""
    warnings: list[str] = []
    explanation_details: dict[str, Any] = {}

    d_count = daily_fefo.days_count if daily_fefo else days_count
    a = average_daily_consumption

    raw_forecast_consumption = a * Decimal(d_count)
    raw_safety_stock = a * Decimal(service_days)
    forecast_consumption = raw_forecast_consumption.quantize(_QTY_QUANT, rounding=ROUND_HALF_UP)
    safety_stock = raw_safety_stock.quantize(_QTY_QUANT, rounding=ROUND_HALF_UP)

    # Точка заказа: a * (L + S). Если L неизвестен -> None
    if lead_time_days is None:
        reorder_point = None
        warnings.append("Срок поставки не задан, точка и дата заказа не рассчитаны")
    else:
        reorder_point = (a * Decimal(lead_time_days + service_days)).quantize(
            _QTY_QUANT, rounding=ROUND_HALF_UP
        )

    # При нулевом потреблении за 90 дней
    if a <= Decimal("0"):
        warnings.append("Потребление за 90 дней отсутствует, закупка не рекомендуется")
        rounded_price = (
            unit_price.quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)
            if unit_price is not None
            else None
        )
        total_cost = _ZERO_PRICE if rounded_price is not None else None
        if rounded_price is None:
            warnings.append("Цена не указана, расчёт стоимости невозможен")
        return OrderRecommendation(
            forecast_consumption=_ZERO_QTY,
            safety_stock=_ZERO_QTY,
            reorder_point=reorder_point,
            stockout_date=None,
            order_date=None,
            recommended_qty=_ZERO_QTY,
            unit_price=rounded_price,
            total_cost=total_cost,
            warnings=tuple(warnings),
            explanation_details={"reason": "zero_consumption"},
        )

    # Определение даты исчерпания и даты заказа
    stockout_date: date | None = None
    order_date: date | None = None

    if daily_fefo is not None:
        stockout_date = daily_fefo.stockout_date

        # Поиск дня падения доступного остатка ниже порога
        # При S = 0 порог — падение до 0 (stockout_date)
        # При S > 0 порог — safety_stock
        threshold = raw_safety_stock if service_days > 0 else _ZERO_QTY
        drop_date: date | None = None

        for step in daily_fefo.daily_steps:
            if service_days > 0 and step.closing_stock < threshold:
                drop_date = step.date
                break
            if service_days == 0 and (
                step.closing_stock <= _ZERO_QTY or step.daily_deficit > _ZERO_QTY
            ):
                drop_date = step.date
                break

        # Если при S = 0 остатка хватает на весь горизонт: stockout_date и order_date равны None
        if service_days == 0 and drop_date is None:
            stockout_date = None
            order_date = None
        elif drop_date is not None and lead_time_days is not None:
            calc_order_date = drop_date - timedelta(days=lead_time_days)
            if calc_order_date <= as_of:
                order_date = as_of
                warnings.append(
                    "Потребность возникает раньше возможного поступления; "
                    "рекомендуется немедленный заказ"
                )
            else:
                order_date = calc_order_date

    # Расчёт потребности P
    # Суммарная потребность на горизонте: forecast_consumption + safety_stock
    # Доступно на покрытие: available_stock + incoming - expired
    if daily_fefo is not None:
        tot_incoming = daily_fefo.total_incoming
        tot_expired = daily_fefo.total_expired
    else:
        tot_incoming = incoming_qty
        tot_expired = _ZERO_QTY

    usable_stock = available_stock + tot_incoming - tot_expired
    p_need = (raw_forecast_consumption + raw_safety_stock) - usable_stock

    if service_days == 0 and (
        daily_fefo is not None and daily_fefo.total_deficit <= _ZERO_QTY and stockout_date is None
    ):
        recommended_qty = _ZERO_QTY
    elif p_need <= _ZERO_QTY:
        recommended_qty = _ZERO_QTY
    else:
        effective_p = p_need
        if min_order_qty is not None and min_order_qty > _ZERO_QTY:
            effective_p = max(effective_p, min_order_qty)

        if package_size is not None and package_size > _ZERO_QTY:
            num_packages = (effective_p / package_size).to_integral_value(rounding=ROUND_CEILING)
            recommended_qty = (num_packages * package_size).quantize(_QTY_QUANT)
        else:
            recommended_qty = effective_p.quantize(_QTY_QUANT, rounding=ROUND_HALF_UP)

    explanation_details["p_need"] = str(p_need)
    explanation_details["usable_stock"] = str(usable_stock)

    # Цена и стоимость
    if unit_price is None:
        final_price = None
        final_cost = None
        warnings.append("Цена не указана, расчёт стоимости невозможен")
    else:
        final_price = unit_price.quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)
        final_cost = (recommended_qty * final_price).quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)

    return OrderRecommendation(
        forecast_consumption=forecast_consumption,
        safety_stock=safety_stock,
        reorder_point=reorder_point,
        stockout_date=stockout_date,
        order_date=order_date,
        recommended_qty=recommended_qty,
        unit_price=final_price,
        total_cost=final_cost,
        warnings=tuple(warnings),
        explanation_details=explanation_details,
    )
