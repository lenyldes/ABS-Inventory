"""Доменные структуры данных для симуляции и валидации наборов исправлений."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.inventory.domain import BatchSnapshot, MovementSnapshot


@dataclass(frozen=True)
class AllocationQuantityChange:
    """Изменение количества в конкретной строке распределения расхода."""

    allocation_id: int
    quantity: Decimal


@dataclass(frozen=True)
class AllocationBatchChange:
    """Смена учётной партии для строки распределения расхода."""

    allocation_id: int
    new_batch_id: int


@dataclass(frozen=True)
class AmendmentOperation:
    """Предложенная операция исправления или отмены складского движения."""

    movement_id: int
    action: str  # "update" или "cancel"
    expected_version: int = 1
    quantity: Decimal | None = None
    operation_date: date | None = None
    doc_number: str | None = None
    location_id: int | None = None
    location_code: str | None = None
    allocation_quantities: tuple[AllocationQuantityChange, ...] | None = None
    allocation_batch_change: AllocationBatchChange | None = None
    raw_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AmendmentBlocker:
    """Блокирующее нарушение, препятствующее подтверждению набора исправлений."""

    code: str
    message: str
    movement_id: int | None = None
    dependent_movement_id: int | None = None
    batch_id: int | None = None
    allocation_id: int | None = None
    deficit_qty: Decimal | None = None
    deficit_date: date | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Преобразует блокирующее нарушение в словарь для ответа API."""
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.movement_id is not None:
            result["movement_id"] = self.movement_id
        if self.dependent_movement_id is not None:
            result["dependent_movement_id"] = self.dependent_movement_id
        if self.batch_id is not None:
            result["batch_id"] = self.batch_id
        if self.allocation_id is not None:
            result["allocation_id"] = self.allocation_id
        if self.deficit_qty is not None:
            result["deficit_qty"] = f"{self.deficit_qty:.3f}"
        if self.deficit_date is not None:
            result["deficit_date"] = self.deficit_date.isoformat()
        if self.details:
            result["details"] = self.details
        return result


@dataclass(frozen=True)
class StockImpact:
    """Разница учетного и доступного остатков по партии до и после применения набора."""

    sku: str
    location: str
    batch_id: int
    current_stock_before: Decimal
    current_stock_after: Decimal
    available_stock_before: Decimal
    available_stock_after: Decimal

    def to_dict(self) -> dict[str, Any]:
        """Преобразует влияние на остаток в словарь для ответа API."""
        return {
            "sku": self.sku,
            "location": self.location,
            "batch_id": self.batch_id,
            "current_stock_before": f"{self.current_stock_before:.3f}",
            "current_stock_after": f"{self.current_stock_after:.3f}",
            "available_stock_before": f"{self.available_stock_before:.3f}",
            "available_stock_after": f"{self.available_stock_after:.3f}",
        }


@dataclass(frozen=True)
class SimulationResult:
    """Результат предварительного расчёта и симуляции набора исправлений."""

    can_apply: bool
    stock_impact: tuple[StockImpact, ...]
    affected_operations: tuple[int, ...]
    blockers: tuple[AmendmentBlocker, ...]
    projected_movements: tuple[MovementSnapshot, ...]
    projected_batches: tuple[BatchSnapshot, ...]
