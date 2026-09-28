"""Pydantic-схемы для запроса и ответа эндпоинта POST /api/forecast."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

AverageQuantity = Annotated[Decimal, Field(max_digits=12, decimal_places=6)]
Quantity = Annotated[Decimal, Field(max_digits=12, decimal_places=3)]
Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]


class ForecastRequest(BaseModel):
    """Схема входного запроса на расчёт прогноза потребности."""

    model_config = ConfigDict(extra="forbid")

    sku: str = Field(..., min_length=1, description="Артикул товара")
    location: str = Field(..., min_length=1, description="Код объекта/склада")
    as_of: date | None = Field(
        default=None,
        description="Контрольная дата актуальности (по умолчанию сегодня по Москве)",
    )
    horizon_days: int | None = Field(
        default=None,
        description="Горизонт прогноза в днях (>= 1, взаимоисключающий с horizon_months)",
    )
    horizon_months: int | None = Field(
        default=None,
        description="Горизонт прогноза в месяцах (>= 1, взаимоисключающий с horizon_days)",
    )
    service_days: int = Field(
        default=0,
        description="Дни страхового запаса (>= 0, по умолчанию 0)",
    )


class DailyForecastItem(BaseModel):
    """Показатели посуточного FEFO-моделирования."""

    date: date
    consumption: Decimal
    incoming: Decimal
    expired: Decimal
    closing_stock: Decimal
    daily_deficit: Decimal

    @field_serializer(
        "consumption",
        "incoming",
        "expired",
        "closing_stock",
        "daily_deficit",
        when_used="json",
    )
    def serialize_quantity(self, value: Decimal) -> str:
        """Округляет суточные показатели только при формировании JSON-ответа."""
        return str(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


class ExplanationItemSchema(BaseModel):
    """Элемент исходных данных в объекте explanation."""

    name: str
    value: Any
    source: str


class ForecastExplanationSchema(BaseModel):
    """Структурированное объяснение прогноза."""

    data_used: list[ExplanationItemSchema]
    formulas: list[str]
    assumptions: list[str]


class ForecastResponse(BaseModel):
    """Схема ответа с результатами расчёта прогноза и параметров закупки."""

    sku: str
    location: str
    as_of: date
    horizon_start: date
    horizon_end: date
    days_count: int

    average_daily_consumption: AverageQuantity
    forecast_consumption: Quantity
    safety_stock: Quantity
    current_stock: Quantity
    available_stock: Quantity
    incoming_qty: Quantity

    stockout_date: date | None = None
    order_date: date | None = None
    reorder_point: Quantity | None = None
    recommended_qty: Quantity
    unit_price: Money | None = None
    total_cost: Money | None = None

    is_history_complete: bool
    history_days: int
    daily_forecast: list[DailyForecastItem]
    explanation: ForecastExplanationSchema
    warnings: list[str]
