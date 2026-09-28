"""Неизменяемые структуры данных и снимки доменных сущностей склада."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class BatchSnapshot:
    """Снимок учётной партии."""

    id: int
    item_id: int
    location_id: int
    batch_number: str
    receipt_date: date
    expiry_date: date | None
    unit_price: Decimal
    receipt_doc_number: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class AllocationSnapshot:
    """Снимок строки распределения расхода по партии."""

    batch_id: int
    quantity: Decimal
    unit_price: Decimal
    id: int | None = None
    movement_id: int | None = None


@dataclass(frozen=True)
class MovementSnapshot:
    """Снимок движения склада."""

    operation_date: date
    item_id: int
    location_id: int
    type: str  # receipt, consume, writeoff, return, correction
    quantity: Decimal
    doc_number: str
    id: int | None = None
    created_at: datetime | None = None
    batch_id: int | None = None
    reason: str | None = None
    parent_movement_id: int | None = None
    parent_allocation_id: int | None = None
    purchase_order_id: int | None = None
    supplier_id: int | None = None
    status: str = "active"
    allocations: tuple[AllocationSnapshot, ...] = ()


@dataclass(frozen=True)
class BatchStock:
    """Остаток по конкретной партии на контрольную дату."""

    batch_id: int
    batch_number: str
    receipt_date: date
    expiry_date: date | None
    unit_price: Decimal
    receipt_doc_number: str
    current_quantity: Decimal
    available_quantity: Decimal
    expired_quantity: Decimal


@dataclass(frozen=True)
class StockBalance:
    """Сводный баланс остатков товара на объекте на контрольную дату."""

    current_stock: Decimal
    available_stock: Decimal
    expired_stock: Decimal
    nearest_expiry_date: date | None
    batches: tuple[BatchStock, ...] = ()


@dataclass(frozen=True)
class MovementWarning:
    """Предупреждение по складской операции."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
