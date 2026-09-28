"""Маршруты API расчёта прогноза потребности и закупок."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.forecast_schemas import (
    DailyForecastItem,
    ExplanationItemSchema,
    ForecastExplanationSchema,
    ForecastRequest,
    ForecastResponse,
)
from app.core.database import get_db
from app.core.timezone import today_in_moscow
from app.forecasting.consumption import calculate_consumption_metrics
from app.forecasting.daily_fefo import simulate_daily_fefo
from app.forecasting.explanation import build_forecast_explanation
from app.forecasting.order_calculation import calculate_order_recommendation
from app.forecasting.procurement_repository import load_forecast_inputs
from app.inventory.calculator import calculate_stock_balance

router = APIRouter(prefix="/api/forecast", tags=["Forecasting"])

_ZERO_QTY = Decimal("0.000")
_QTY_QUANT = Decimal("0.001")


def _validate_forecast_request(req: ForecastRequest) -> None:
    """Проверяет корректность параметров горизонта и страхового запаса."""
    if req.horizon_days is not None and req.horizon_months is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметры horizon_days и horizon_months взаимоисключающие",
        )
    if req.horizon_days is None and req.horizon_months is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Необходимо указать horizon_days либо horizon_months",
        )
    if req.horizon_days is not None and req.horizon_days < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр horizon_days должен быть не менее 1",
        )
    if req.horizon_months is not None and req.horizon_months < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр horizon_months должен быть не менее 1",
        )
    if req.service_days < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр service_days не может быть отрицательным",
        )


@router.post(
    "",
    response_model=ForecastResponse,
    summary="Расчёт прогноза потребности и плана закупок",
)
def post_forecast(
    req: ForecastRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ForecastResponse:
    """Вычисляет показатели прогноза, суточный план FEFO и рекомендацию по закупке."""
    _validate_forecast_request(req)

    calc_as_of = req.as_of or today_in_moscow()

    inputs = load_forecast_inputs(
        session=db,
        sku=req.sku,
        location_code=req.location,
        as_of=calc_as_of,
    )

    balance = calculate_stock_balance(
        batches=inputs.batches,
        movements=inputs.movements,
        as_of=calc_as_of,
    )

    batch_stocks = {b.batch_id: b.available_quantity for b in balance.batches}

    consumption_metrics = calculate_consumption_metrics(
        movements=inputs.movements,
        as_of=calc_as_of,
        available_stock=balance.available_stock,
    )

    incoming_qty = sum(
        (o.pending_qty for o in inputs.procurement_context.pending_orders),
        _ZERO_QTY,
    ).quantize(_QTY_QUANT)

    daily_fefo = simulate_daily_fefo(
        as_of=calc_as_of,
        average_daily_consumption=consumption_metrics.average_daily_consumption,
        batches=inputs.batches,
        batch_stocks=batch_stocks,
        incoming_orders=inputs.procurement_context.pending_orders,
        horizon_days=req.horizon_days,
        horizon_months=req.horizon_months,
    )

    order_rec = calculate_order_recommendation(
        as_of=calc_as_of,
        average_daily_consumption=consumption_metrics.average_daily_consumption,
        days_count=daily_fefo.days_count,
        service_days=req.service_days,
        lead_time_days=inputs.procurement_context.lead_time_days,
        package_size=inputs.procurement_context.package_size,
        min_order_qty=inputs.procurement_context.min_order_qty,
        unit_price=inputs.procurement_context.unit_price,
        available_stock=balance.available_stock,
        daily_fefo=daily_fefo,
        incoming_qty=incoming_qty,
    )

    explanation_domain, all_warnings = build_forecast_explanation(
        as_of=calc_as_of,
        days_count=daily_fefo.days_count,
        service_days=req.service_days,
        balance=balance,
        consumption_metrics=consumption_metrics,
        movements=inputs.movements,
        daily_fefo=daily_fefo,
        procurement_context=inputs.procurement_context,
        order_rec=order_rec,
    )

    daily_items = [
        DailyForecastItem(
            date=s.date,
            consumption=s.consumption,
            incoming=s.incoming,
            expired=s.expired,
            closing_stock=s.closing_stock,
            daily_deficit=s.daily_deficit,
        )
        for s in daily_fefo.daily_steps
    ]

    explanation_schema = ForecastExplanationSchema(
        data_used=[
            ExplanationItemSchema(name=item.name, value=item.value, source=item.source)
            for item in explanation_domain.data_used
        ],
        formulas=list(explanation_domain.formulas),
        assumptions=list(explanation_domain.assumptions),
    )

    return ForecastResponse(
        sku=inputs.item.sku,
        location=inputs.location.code,
        as_of=calc_as_of,
        horizon_start=daily_fefo.horizon_start,
        horizon_end=daily_fefo.horizon_end,
        days_count=daily_fefo.days_count,
        average_daily_consumption=consumption_metrics.average_daily_consumption,
        forecast_consumption=order_rec.forecast_consumption,
        safety_stock=order_rec.safety_stock,
        current_stock=balance.current_stock.quantize(_QTY_QUANT),
        available_stock=balance.available_stock.quantize(_QTY_QUANT),
        incoming_qty=incoming_qty,
        stockout_date=order_rec.stockout_date,
        order_date=order_rec.order_date,
        reorder_point=order_rec.reorder_point,
        recommended_qty=order_rec.recommended_qty,
        unit_price=order_rec.unit_price,
        total_cost=order_rec.total_cost,
        is_history_complete=consumption_metrics.is_history_complete,
        history_days=consumption_metrics.history_days,
        daily_forecast=daily_items,
        explanation=explanation_schema,
        warnings=all_warnings,
    )
