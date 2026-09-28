"""Общие проверки и вспомогательные функции для складских операций."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.inventory.exceptions import (
    DocumentDuplicateError,
    InvalidMovementError,
)
from app.inventory.repository import (
    acquire_stock_lock,
    batch_to_snapshot,
    get_batches,
    get_movements_with_allocations,
    is_doc_number_active,
    movement_to_snapshot,
)
from app.models.catalog import Item, Location
from app.models.inventory import Batch, Movement, MovementAllocation

_ZERO = Decimal("0.000")


@dataclass(frozen=True)
class MovementExecutionResult:
    """Результат выполнения складской операции."""

    movement: Movement
    current_stock: Decimal
    available_stock: Decimal
    allocations: tuple[MovementAllocation, ...] = ()


def validate_common_rules(
    session: Session,
    item: Item,
    location: Location,
    operation_date: date,
    quantity: Decimal,
    doc_number: str,
    *,
    allow_negative: bool = False,
) -> None:
    """Общие проверки: блокировка, дата не в будущем, уникальность номера, неделимость штук."""
    acquire_stock_lock(session, item.id, location.id)

    today = date.today()
    if operation_date > today:
        raise InvalidMovementError(
            f"Дата операции {operation_date.isoformat()} не может быть "
            f"в будущем (сегодня {today.isoformat()})",
            code="FUTURE_DATE",
            details={
                "operation_date": operation_date.isoformat(),
                "today": today.isoformat(),
            },
        )

    if not allow_negative and quantity <= _ZERO:
        raise InvalidMovementError(
            f"Количество должно быть строго больше нуля: получено {quantity}",
            code="INVALID_QUANTITY",
            details={"quantity": str(quantity)},
        )

    if allow_negative and quantity == _ZERO:
        raise InvalidMovementError(
            "Количество корректировки не может быть равно нулю",
            code="ZERO_QUANTITY",
            details={"quantity": str(quantity)},
        )

    # Проверка неделимости для единиц измерения «шт»
    if item.unit.strip().lower() in ("шт", "шт.", "pcs", "piece"):
        if quantity % Decimal("1") != _ZERO:
            raise InvalidMovementError(
                f"Для единицы измерения '{item.unit}' допускаются "
                f"только целые значения: получено {quantity}",
                code="FRACTIONAL_PIECES",
                details={"unit": item.unit, "quantity": str(quantity)},
            )

    if is_doc_number_active(session, location.id, doc_number):
        raise DocumentDuplicateError(doc_number=doc_number, location_code=location.code)


def load_history(
    session: Session,
    item_id: int,
    location_id: int,
) -> tuple[list[Batch], list[Movement], list[BatchSnapshot], list[MovementSnapshot]]:
    """Загружает доменные снимки партий и движений."""
    batches = get_batches(session, item_id, location_id)
    movements = get_movements_with_allocations(session, item_id, location_id)
    b_snaps = [batch_to_snapshot(b) for b in batches]
    m_snaps = [movement_to_snapshot(m) for m in movements]
    return batches, movements, b_snaps, m_snaps
