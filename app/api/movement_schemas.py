"""Pydantic-схемы для складских движений (POST /api/movements, GET /api/movements)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MovementType = Literal["receipt", "consume", "writeoff", "return", "correction"]


class MovementCreateRequest(BaseModel):
    """Схема запроса на регистрацию складского движения."""

    model_config = ConfigDict(extra="forbid")

    operation_date: date
    sku: str = Field(..., min_length=1, max_length=64)
    location: str = Field(..., min_length=1, max_length=64)
    type: MovementType
    quantity: Decimal
    doc_number: str = Field(..., min_length=1, max_length=64)
    batch_number: str | None = Field(default=None, max_length=128)
    expiry_date: date | None = None
    unit_price: Decimal | None = None
    batch_id: int | None = None
    reason: str | None = None
    parent_movement_id: int | None = None
    parent_allocation_id: int | None = None
    purchase_order_id: int | None = None
    supplier_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_type_specific_rules(self) -> "MovementCreateRequest":
        """Проверяет допустимость и обязательность полей по типу операции."""
        m_type = self.type
        qty = self.quantity
        zero = Decimal("0.000")

        if m_type == "receipt":
            if qty <= zero:
                raise ValueError("Количество поступления должно быть больше нуля")
            if not self.batch_number or not self.batch_number.strip():
                raise ValueError("Для поступления (receipt) обязателен batch_number")
            if self.unit_price is None:
                raise ValueError("Для поступления (receipt) обязателен unit_price")
            if self.batch_id is not None:
                raise ValueError("Для поступления (receipt) запрещён batch_id")
            if self.parent_movement_id is not None or self.parent_allocation_id is not None:
                raise ValueError(
                    "Для поступления (receipt) запрещены parent_movement_id и parent_allocation_id"
                )

        elif m_type == "consume":
            if qty <= zero:
                raise ValueError("Количество расхода должно быть больше нуля")
            if self.batch_id is not None or self.batch_number is not None:
                raise ValueError(
                    "Для расхода (consume) запрещён выбор партии (batch_id, batch_number)"
                )
            if self.unit_price is not None:
                raise ValueError("Для расхода (consume) запрещён unit_price")
            if self.parent_movement_id is not None or self.parent_allocation_id is not None:
                raise ValueError(
                    "Для расхода (consume) запрещены parent_movement_id и parent_allocation_id"
                )

        elif m_type == "writeoff":
            if qty <= zero:
                raise ValueError("Количество списания должно быть больше нуля")
            if self.batch_id is None:
                raise ValueError("Для списания (writeoff) обязателен batch_id")
            if not self.reason or not self.reason.strip():
                raise ValueError("Для списания (writeoff) обязательна причина (reason)")
            if self.batch_number is not None:
                raise ValueError("Для списания (writeoff) запрещён batch_number")
            if self.parent_movement_id is not None or self.parent_allocation_id is not None:
                raise ValueError(
                    "Для списания (writeoff) запрещены parent_movement_id и parent_allocation_id"
                )

        elif m_type == "return":
            if qty <= zero:
                raise ValueError("Количество возврата должно быть больше нуля")
            if self.parent_movement_id is None:
                raise ValueError("Для возврата (return) обязателен parent_movement_id")
            if self.parent_allocation_id is None:
                raise ValueError("Для возврата (return) обязателен parent_allocation_id")
            if self.batch_id is not None or self.batch_number is not None:
                raise ValueError(
                    "Для возврата (return) запрещён выбор партии (batch_id, batch_number)"
                )
            if self.unit_price is not None:
                raise ValueError("Для возврата (return) запрещён unit_price")

        elif m_type == "correction":
            if qty == zero:
                raise ValueError("Количество корректировки не может быть равно нулю")
            if self.batch_id is None:
                raise ValueError("Для корректировки (correction) обязателен batch_id")
            if not self.reason or not self.reason.strip():
                raise ValueError("Для корректировки (correction) обязательна причина (reason)")
            if self.batch_number is not None:
                raise ValueError("Для корректировки (correction) запрещён batch_number")
            if self.parent_movement_id is not None or self.parent_allocation_id is not None:
                raise ValueError(
                    "Для корректировки (correction) запрещены parent_movement_id и "
                    "parent_allocation_id"
                )

        return self


class AllocationResponse(BaseModel):
    """Строка распределения расхода/возврата по партии."""

    id: int
    batch_id: int
    quantity: Decimal
    unit_price: Decimal


class MovementResponse(BaseModel):
    """Схема ответа успешной регистрации движения (201 Created)."""

    id: int
    operation_date: date
    sku: str
    location: str
    type: str
    quantity: Decimal
    doc_number: str
    current_stock: Decimal
    available_stock: Decimal
    allocations: list[AllocationResponse] = []


class MovementWarningResponse(BaseModel):
    """Схема предупреждения по движению расхода."""

    code: str
    message: str
    details: dict[str, Any] = {}


class MovementListItem(BaseModel):
    """Элемент журнала складских движений."""

    id: int
    operation_date: date
    created_at: datetime
    sku: str
    location: str
    type: str
    quantity: Decimal
    doc_number: str
    reason: str | None = None
    allocations: list[AllocationResponse] = []
    warnings: list[MovementWarningResponse] = []


class MovementListResponse(BaseModel):
    """Схема ответа журнала складских движений."""

    items: list[MovementListItem]
    total: int
    limit: int
    offset: int
