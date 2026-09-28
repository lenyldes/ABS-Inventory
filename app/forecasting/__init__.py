"""Доменный модуль прогнозирования спроса и расчёта потребности."""

from app.forecasting.alerts import calculate_item_alerts
from app.forecasting.consumption import calculate_consumption_metrics
from app.forecasting.daily_fefo import simulate_daily_fefo
from app.forecasting.domain import (
    AlertItem,
    ConsumptionMetrics,
    DailyFefoResult,
    ForecastExplanation,
    ForecastResult,
    OrderRecommendation,
)
from app.forecasting.explanation import build_forecast_explanation
from app.forecasting.order_calculation import calculate_order_recommendation
from app.forecasting.procurement_repository import (
    ForecastInputs,
    load_forecast_inputs,
    load_procurement_context,
)

__all__ = [
    "AlertItem",
    "ConsumptionMetrics",
    "DailyFefoResult",
    "ForecastExplanation",
    "ForecastInputs",
    "ForecastResult",
    "OrderRecommendation",
    "build_forecast_explanation",
    "calculate_consumption_metrics",
    "calculate_item_alerts",
    "calculate_order_recommendation",
    "load_forecast_inputs",
    "load_procurement_context",
    "simulate_daily_fefo",
]
