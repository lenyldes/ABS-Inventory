"""Pydantic-схемы для сводных и детальных остатков (GET /api/stock, GET /api/stock/{sku})."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class StockSummaryItem(BaseModel):
    """Строка сводного остатка по товару и объекту."""

    sku: str
    name: str
    category: str
    unit: str
    location: str
    current_stock: Decimal
    available_stock: Decimal
    expired_stock: Decimal
    average_daily_consumption: Decimal | None = None
    days_of_stock: Decimal | None = None
    nearest_expiry_date: date | None = None


class StockSummaryResponse(BaseModel):
    """Схема ответа сводного списка остатков."""

    items: list[StockSummaryItem]
    total: int
    limit: int
    offset: int


class BatchStockDetail(BaseModel):
    """Детализация остатка по конкретной партии."""

    batch_id: int
    batch_number: str
    receipt_date: date
    expiry_date: date | None = None
    unit_price: Decimal
    quantity: Decimal
    available_quantity: Decimal
    receipt_doc_number: str


class LocationStockDetail(BaseModel):
    """Остаток и партии товара на конкретном объекте."""

    location: str
    current_stock: Decimal
    available_stock: Decimal
    expired_stock: Decimal
    batches: list[BatchStockDetail]


class StockSkuResponse(BaseModel):
    """Схема ответа детального остатка по конкретному SKU."""

    sku: str
    name: str
    category: str
    unit: str
    locations: list[LocationStockDetail]
