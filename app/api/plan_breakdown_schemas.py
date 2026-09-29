"""Схемы аналитических разрезов и бюджета для плана закупок."""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

Quantity = Annotated[Decimal, Field(max_digits=12, decimal_places=3)]
Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2)]


class PlanMonthlyBreakdownItem(BaseModel):
    """Группировка бюджета по календарному месяцу даты заказа."""

    month: str
    year: int
    month_number: int
    known_total: Money
    total_cost: Money | None = None
    total_quantity: Quantity = Decimal("0.000")
    items_count: int
    unknown_price_count: int = 0
    unpriced_items_count: int | None = None
    is_price_complete: bool = True
    has_unpriced_items: bool = False
    is_partial: bool

    @model_validator(mode="after")
    def populate_monthly_defaults(self) -> "PlanMonthlyBreakdownItem":
        """Синхронизирует алиасы стоимостей и полноты цены."""
        if self.total_cost is None:
            self.total_cost = self.known_total
        elif self.known_total is None:
            self.known_total = self.total_cost
        if self.unpriced_items_count is None:
            self.unpriced_items_count = self.unknown_price_count
        elif self.unknown_price_count == 0 and self.unpriced_items_count > 0:
            self.unknown_price_count = self.unpriced_items_count
        if self.has_unpriced_items is False and not self.is_price_complete:
            self.has_unpriced_items = True
        return self


class PlanSkuBreakdownItem(BaseModel):
    """Группировка бюджета по артикулу (SKU)."""

    sku: str
    name: str | None = None
    category: str | None = None
    known_total: Money
    total_cost: Money | None = None
    total_quantity: Quantity = Decimal("0.000")
    items_count: int
    unknown_price_count: int = 0
    unpriced_items_count: int | None = None
    is_price_complete: bool = True
    has_unpriced_items: bool = False

    @model_validator(mode="after")
    def populate_sku_defaults(self) -> "PlanSkuBreakdownItem":
        """Синхронизирует алиасы стоимостей и полноты цены."""
        if self.total_cost is None:
            self.total_cost = self.known_total
        elif self.known_total is None:
            self.known_total = self.total_cost
        if self.unpriced_items_count is None:
            self.unpriced_items_count = self.unknown_price_count
        elif self.unknown_price_count == 0 and self.unpriced_items_count > 0:
            self.unknown_price_count = self.unpriced_items_count
        if self.has_unpriced_items is False and not self.is_price_complete:
            self.has_unpriced_items = True
        return self


class PlanCategoryBreakdownItem(BaseModel):
    """Группировка бюджета по категории товара."""

    category: str
    known_total: Money
    total_cost: Money | None = None
    total_quantity: Quantity = Decimal("0.000")
    items_count: int
    unknown_price_count: int = 0
    unpriced_items_count: int | None = None
    is_price_complete: bool = True
    has_unpriced_items: bool = False

    @model_validator(mode="after")
    def populate_category_defaults(self) -> "PlanCategoryBreakdownItem":
        """Синхронизирует алиасы стоимостей и полноты цены."""
        if self.total_cost is None:
            self.total_cost = self.known_total
        elif self.known_total is None:
            self.known_total = self.total_cost
        if self.unpriced_items_count is None:
            self.unpriced_items_count = self.unknown_price_count
        elif self.unknown_price_count == 0 and self.unpriced_items_count > 0:
            self.unknown_price_count = self.unpriced_items_count
        if self.has_unpriced_items is False and not self.is_price_complete:
            self.has_unpriced_items = True
        return self


class PlanLocationBreakdownItem(BaseModel):
    """Группировка бюджета по объекту (складу)."""

    location: str
    name: str | None = None
    known_total: Money
    total_cost: Money | None = None
    total_quantity: Quantity = Decimal("0.000")
    items_count: int
    unknown_price_count: int = 0
    unpriced_items_count: int | None = None
    is_price_complete: bool = True
    has_unpriced_items: bool = False

    @model_validator(mode="after")
    def populate_location_defaults(self) -> "PlanLocationBreakdownItem":
        """Синхронизирует алиасы стоимостей и полноты цены."""
        if self.total_cost is None:
            self.total_cost = self.known_total
        elif self.known_total is None:
            self.known_total = self.total_cost
        if self.unpriced_items_count is None:
            self.unpriced_items_count = self.unknown_price_count
        elif self.unknown_price_count == 0 and self.unpriced_items_count > 0:
            self.unknown_price_count = self.unpriced_items_count
        if self.has_unpriced_items is False and not self.is_price_complete:
            self.has_unpriced_items = True
        return self


class PlanUndatedBreakdownItem(BaseModel):
    """Группа позиций без даты заказа."""

    known_total: Money
    total_cost: Money | None = None
    total_quantity: Quantity = Decimal("0.000")
    items_count: int
    unknown_price_count: int = 0
    unpriced_items_count: int | None = None
    is_price_complete: bool = True
    has_unpriced_items: bool = False

    @model_validator(mode="after")
    def populate_undated_defaults(self) -> "PlanUndatedBreakdownItem":
        """Синхронизирует алиасы стоимостей и полноты цены."""
        if self.total_cost is None:
            self.total_cost = self.known_total
        elif self.known_total is None:
            self.known_total = self.total_cost
        if self.unpriced_items_count is None:
            self.unpriced_items_count = self.unknown_price_count
        elif self.unknown_price_count == 0 and self.unpriced_items_count > 0:
            self.unknown_price_count = self.unpriced_items_count
        if self.has_unpriced_items is False and not self.is_price_complete:
            self.has_unpriced_items = True
        return self


class PlanBudgetSchema(BaseModel):
    """Сводный бюджет и аналитические разрезы плана закупок."""

    known_total: Money
    total_cost: Money | None = None
    total_quantity: Quantity = Decimal("0.000")
    is_price_complete: bool = True
    is_dates_complete: bool = True
    unknown_price_count: int = 0
    unpriced_items_count: int | None = None
    has_unpriced_items: bool = False
    undated_count: int = 0
    by_month: list[PlanMonthlyBreakdownItem] = Field(default_factory=list)
    undated: PlanUndatedBreakdownItem
    by_sku: list[PlanSkuBreakdownItem] = Field(default_factory=list)
    by_category: list[PlanCategoryBreakdownItem] = Field(default_factory=list)
    by_location: list[PlanLocationBreakdownItem] = Field(default_factory=list)
    budget_limit: Money | None = None
    limit_status: str | None = None
    limit_difference: Money | None = None

    @model_validator(mode="after")
    def populate_budget_defaults(self) -> "PlanBudgetSchema":
        """Синхронизирует алиасы стоимостей и полноты цены."""
        if self.total_cost is None:
            self.total_cost = self.known_total
        elif self.known_total is None:
            self.known_total = self.total_cost
        if self.unpriced_items_count is None:
            self.unpriced_items_count = self.unknown_price_count
        elif self.unknown_price_count == 0 and self.unpriced_items_count > 0:
            self.unknown_price_count = self.unpriced_items_count
        if self.has_unpriced_items is False and not self.is_price_complete:
            self.has_unpriced_items = True
        return self
