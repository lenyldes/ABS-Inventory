"""Проверка исторической обеспеченности и допустимости движений по времени."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from decimal import Decimal

from app.inventory.calculator import sort_movements_chronological
from app.inventory.domain import (
    BatchSnapshot,
    MovementSnapshot,
)
from app.inventory.exceptions import (
    ExcessReturnError,
    HistoricalSufficiencyError,
    InvalidMovementError,
)

_ZERO = Decimal("0.000")


def validate_history_sufficiency(
    batches: Sequence[BatchSnapshot],
    existing_movements: Iterable[MovementSnapshot],
    new_movement: MovementSnapshot | None = None,
) -> None:
    """Проверяет неотрицательность остатков по дням и партиям при добавлении движения.

    Если на какую-либо дату (включая будущие даты относительно операции) возникает дефицит,
    выбрасывает HistoricalSufficiencyError с указанием даты и конфликтующего документа.
    """
    all_movements = [m for m in existing_movements if m.status == "active"]
    if new_movement is not None and new_movement.status == "active":
        all_movements.append(new_movement)

    sorted_movements = sort_movements_chronological(all_movements)

    # Карта партий
    batch_map = {b.id: b for b in batches}
    if new_movement and new_movement.batch_id and new_movement.batch_id not in batch_map:
        # Партия нового движения (например, прихода)
        pass

    # Балансы по партиям
    batch_balances: dict[int, Decimal] = defaultdict(lambda: _ZERO)
    # Суммарные возвраты по каждой строке расхода (parent_allocation_id -> total_returned)
    returns_by_alloc: dict[int, Decimal] = defaultdict(lambda: _ZERO)
    # Доступные для возврата количества по строкам расхода (alloc_id -> original_qty)
    alloc_original_qty: dict[int, Decimal] = {}
    alloc_operation_dates: dict[int, MovementSnapshot] = {}

    for m in sorted_movements:
        if m.type == "receipt":
            if m.batch_id is not None:
                batch_balances[m.batch_id] += m.quantity

        elif m.type == "consume":
            for alloc in m.allocations:
                if alloc.id is not None:
                    alloc_original_qty[alloc.id] = alloc.quantity
                    alloc_operation_dates[alloc.id] = m

                batch_balances[alloc.batch_id] -= alloc.quantity
                if batch_balances[alloc.batch_id] < _ZERO:
                    deficit = abs(batch_balances[alloc.batch_id])
                    raise HistoricalSufficiencyError(
                        deficit_date=m.operation_date,
                        deficit_qty=deficit,
                        conflicting_doc_number=m.doc_number,
                        batch_id=alloc.batch_id,
                    )

        elif m.type == "writeoff":
            if m.batch_id is not None:
                batch_balances[m.batch_id] -= m.quantity
                if batch_balances[m.batch_id] < _ZERO:
                    deficit = abs(batch_balances[m.batch_id])
                    raise HistoricalSufficiencyError(
                        deficit_date=m.operation_date,
                        deficit_qty=deficit,
                        conflicting_doc_number=m.doc_number,
                        batch_id=m.batch_id,
                    )

        elif m.type == "return":
            if m.parent_allocation_id is not None:
                orig_qty = alloc_original_qty.get(m.parent_allocation_id)
                parent_mv = alloc_operation_dates.get(m.parent_allocation_id)
                if orig_qty is not None:
                    already_returned = returns_by_alloc[m.parent_allocation_id]
                    max_allowed = orig_qty - already_returned
                    if m.quantity > max_allowed:
                        raise ExcessReturnError(
                            requested_return=m.quantity,
                            max_allowed_return=max_allowed,
                            parent_allocation_id=m.parent_allocation_id,
                        )
                    returns_by_alloc[m.parent_allocation_id] += m.quantity
                if parent_mv is not None and m.operation_date < parent_mv.operation_date:
                    raise InvalidMovementError(
                        f"Дата возврата {m.operation_date} не может предшествовать "
                        f"дате расхода {parent_mv.operation_date}",
                        code="INVALID_RETURN_DATE",
                    )

            if m.batch_id is not None:
                batch_balances[m.batch_id] += m.quantity

        elif m.type == "correction":
            if m.batch_id is not None:
                batch_balances[m.batch_id] += m.quantity
                if batch_balances[m.batch_id] < _ZERO:
                    deficit = abs(batch_balances[m.batch_id])
                    raise HistoricalSufficiencyError(
                        deficit_date=m.operation_date,
                        deficit_qty=deficit,
                        conflicting_doc_number=m.doc_number,
                        batch_id=m.batch_id,
                    )
