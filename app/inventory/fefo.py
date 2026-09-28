"""Логика распределения по FEFO и выявления исторических отклонений."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from app.inventory.calculator import (
    calculate_batch_stocks,
    sort_batches_fefo,
)
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
    MovementWarning,
)
from app.inventory.exceptions import InsufficientStockError

_ZERO = Decimal("0.000")


def allocate_fefo(
    requested_qty: Decimal,
    batches: Sequence[BatchSnapshot],
    movements_prior: Sequence[MovementSnapshot],
    operation_date: date,
) -> tuple[AllocationSnapshot, ...]:
    """Распределяет запрошенное количество расхода по партиям по правилу FEFO."""
    # Рассчитываем остатки партий на дату операции с учётом предшествующих движений
    batch_stocks = calculate_batch_stocks(
        batches=batches,
        movements=movements_prior,
        as_of=operation_date,
        include_zero=False,
    )

    # Отбираем партии с доступным (непросроченным) остатком
    eligible_batches: list[BatchSnapshot] = []
    for b in batches:
        if b.id in batch_stocks and batch_stocks[b.id].available_quantity > _ZERO:
            eligible_batches.append(b)

    # Сортируем кандидатов строго по FEFO
    sorted_candidates = sort_batches_fefo(eligible_batches)

    total_available = sum(
        (batch_stocks[b.id].available_quantity for b in sorted_candidates),
        _ZERO,
    )
    if total_available < requested_qty:
        raise InsufficientStockError(requested=requested_qty, available=total_available)

    remaining = requested_qty
    allocations: list[AllocationSnapshot] = []

    for b in sorted_candidates:
        avail = batch_stocks[b.id].available_quantity
        take_qty = min(remaining, avail)
        allocations.append(
            AllocationSnapshot(
                batch_id=b.id,
                quantity=take_qty,
                unit_price=b.unit_price,
            )
        )
        remaining -= take_qty
        if remaining <= _ZERO:
            break

    return tuple(allocations)


def detect_fefo_deviation(
    consume_movement: MovementSnapshot,
    batches: Sequence[BatchSnapshot],
    movements_prior: Sequence[MovementSnapshot],
) -> list[MovementWarning]:
    """Проверяет, отличается ли сохранённое распределение расхода от актуального FEFO."""
    if consume_movement.type != "consume":
        return []

    try:
        ideal_allocations = allocate_fefo(
            requested_qty=consume_movement.quantity,
            batches=batches,
            movements_prior=movements_prior,
            operation_date=consume_movement.operation_date,
        )
    except InsufficientStockError:
        return []

    actual_batch_ids = [a.batch_id for a in consume_movement.allocations]
    ideal_batch_ids = [a.batch_id for a in ideal_allocations]

    # Сравниваем состав партий
    if actual_batch_ids == ideal_batch_ids:
        # Также проверяем совпадение количеств по каждой партии
        actual_map = {a.batch_id: a.quantity for a in consume_movement.allocations}
        ideal_map = {a.batch_id: a.quantity for a in ideal_allocations}
        if actual_map == ideal_map:
            return []

    preceding = [b_id for b_id in ideal_batch_ids if b_id not in actual_batch_ids]
    if not preceding:
        preceding = ideal_batch_ids

    warning = MovementWarning(
        code="fefo_deviation",
        message=(
            "Фактическая выдача отличается от порядка FEFO из-за позднее "
            "зарегистрированного прихода"
        ),
        details={
            "actual_batch_ids": actual_batch_ids,
            "fefo_batch_ids": ideal_batch_ids,
            "preceding_batch_ids": preceding,
        },
    )
    return [warning]
