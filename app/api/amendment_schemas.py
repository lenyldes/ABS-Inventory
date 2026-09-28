"""Pydantic-схемы для предварительного просмотра и подтверждения наборов исправлений."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AllocationQuantityItem(BaseModel):
    """Строка изменения количества конкретного распределения расхода."""

    allocation_id: int
    quantity: Decimal


class OperationItem(BaseModel):
    """Элемент операции исправления или отмены движения."""

    movement_id: int
    action: Literal["update", "cancel"]
    expected_version: int = 1
    fields: dict[str, Any] | None = None


class AmendmentPreviewRequest(BaseModel):
    """Схема запроса на предварительный просмотр набора исправлений."""

    model_config = ConfigDict(extra="ignore")

    reason: str | None = None
    operations: list[OperationItem] | None = None


class StockImpactItem(BaseModel):
    """Элемент разницы учётного и доступного остатков по партии."""

    sku: str
    location: str
    batch_id: int
    current_stock_before: Decimal
    current_stock_after: Decimal
    available_stock_before: Decimal
    available_stock_after: Decimal


class AmendmentBlockerItem(BaseModel):
    """Блокирующее нарушение при симуляции набора исправлений."""

    code: str
    message: str
    movement_id: int | None = None
    dependent_movement_id: int | None = None
    batch_id: int | None = None
    allocation_id: int | None = None
    deficit_qty: Decimal | None = None
    deficit_date: date | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AmendmentPreviewResponse(BaseModel):
    """Схема ответа предварительного просмотра набора исправлений (200 OK)."""

    preview_id: str
    version_signature: str
    can_apply: bool
    stock_impact: list[StockImpactItem]
    affected_operations: list[int]
    blockers: list[AmendmentBlockerItem]


class AmendmentConfirmRequest(BaseModel):
    """Схема запроса на подтверждение предварительного просмотра исправлений."""

    preview_id: str
    version_signature: str
    reason: str


class AppliedMovementItem(BaseModel):
    """Запись о применённой версии движения."""

    movement_id: int
    version: int
    action: str


class AmendmentConfirmResponse(BaseModel):
    """Схема ответа успешного подтверждения набора исправлений."""

    status: str
    amendment_id: str
    applied_movements: list[AppliedMovementItem]
