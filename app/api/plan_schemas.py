"""Pydantic-схемы для запроса и ответа эндпоинта POST /api/procurement/plan."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.api.plan_breakdown_schemas import (
    PlanBudgetSchema,
    PlanCategoryBreakdownItem,
    PlanLocationBreakdownItem,
    PlanMonthlyBreakdownItem,
    PlanSkuBreakdownItem,
    PlanUndatedBreakdownItem,
)

Quantity = Annotated[Decimal, Field(max_digits=12, decimal_places=3)]
Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2)]


class PlanRequest(BaseModel):
    """Схема входного запроса на расчёт плана закупок и бюджета."""

    model_config = ConfigDict(extra="forbid")

    as_of: date | None = Field(
        default=None,
        description="Контрольная дата актуальности (по умолчанию сегодня в Europe/Moscow)",
    )
    horizon_months: StrictInt = Field(
        ...,
        description="Горизонт плана в месяцах (только 1, 3, 6 или 12)",
    )
    service_days: StrictInt = Field(
        default=0,
        description="Дни страхового запаса (>= 0, по умолчанию 0)",
    )
    location: str | None = Field(
        default=None,
        description="Код объекта/склада для фильтрации",
    )
    category: str | None = Field(
        default=None,
        description="Категория товаров для фильтрации",
    )
    budget_limit: Decimal | None = Field(
        default=None,
        decimal_places=2,
        max_digits=14,
        description="Лимит бюджета в рублях (>= 0 до копеек)",
    )


class PlanItemSchema(BaseModel):
    """Рекомендуемая позиция плана закупок."""

    sku: str
    category: str
    location: str
    supplier_id: str | None = None
    supplier_name: str | None = None
    supplier: str | None = None
    order_date: date | None = None
    delivery_date: date | None = None
    expected_date: date | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None
    is_undated: bool = Field(default=False, description="Признак недатированной позиции")
    raw_quantity: Quantity
    quantity: Quantity
    recommended_qty: Quantity | None = None
    unit_price: Money | None = None
    price_source: str | None = None
    total_cost: Money | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    item_name: str | None = None
    name: str | None = None
    location_name: str | None = None

    @model_validator(mode="after")
    def populate_defaults(self) -> "PlanItemSchema":
        """Заполняет производные поля для удобства клиентов API."""
        if self.order_date is None:
            self.is_undated = True
        if self.recommended_qty is None:
            self.recommended_qty = self.quantity
        if self.expected_date is None:
            self.expected_date = self.delivery_date
        if self.supplier is None:
            self.supplier = self.supplier_name or self.supplier_id
        if self.name is None:
            self.name = self.item_name
        if self.item_name is None:
            self.item_name = self.name
        return self


class ExistingOrderSnapshotSchema(BaseModel):
    """Снимок оформленного ранее неполученного заказа."""

    order_id: int
    doc_number: str
    sku: str
    location: str
    expected_date: date
    pending_qty: Quantity
    unit_price: Money | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None


class ExplanationItemSchema(BaseModel):
    """Элемент исходных данных в объяснении плана."""

    name: str
    value: Any
    source: str


class PlanExplanationSchema(BaseModel):
    """Структурированное объяснение плана закупок."""

    data_used: list[ExplanationItemSchema] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    incompleteness_reasons: list[str] = Field(
        default_factory=list,
        description="Читаемые причины неполноты исходных данных или расчёта",
    )


class PlanResponse(BaseModel):
    """Схема ответа расчёта плана закупок и бюджета."""

    as_of: date
    horizon_months: int
    service_days: int
    location: str | None = None
    category: str | None = None
    budget_limit: Money | None = None

    horizon_start: date
    horizon_end: date
    days_count: int
    is_first_month_partial: bool
    is_last_month_partial: bool

    items: list[PlanItemSchema] = Field(default_factory=list)
    existing_orders: list[ExistingOrderSnapshotSchema] = Field(default_factory=list)
    budget: PlanBudgetSchema
    explanation: PlanExplanationSchema
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "ExistingOrderSnapshotSchema",
    "ExplanationItemSchema",
    "Money",
    "PlanBudgetSchema",
    "PlanCategoryBreakdownItem",
    "PlanExplanationSchema",
    "PlanItemSchema",
    "PlanLocationBreakdownItem",
    "PlanMonthlyBreakdownItem",
    "PlanRequest",
    "PlanResponse",
    "PlanSkuBreakdownItem",
    "PlanUndatedBreakdownItem",
    "Quantity",
]
