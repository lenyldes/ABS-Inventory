"""Чистые функции расчёта остатков партий и сводных балансов склада."""

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal

from app.inventory.domain import (
    BatchSnapshot,
    BatchStock,
    MovementSnapshot,
    StockBalance,
)

# Бизнес-приоритет типов движений внутри одной даты:
# receipt / return -> consume / writeoff -> correction
_TYPE_PRIORITY: dict[str, int] = {
    "receipt": 1,
    "return": 1,
    "consume": 2,
    "writeoff": 2,
    "correction": 3,
}

_ZERO_QTY = Decimal("0.000")


def movement_sort_key(
    movement: MovementSnapshot,
) -> tuple[date, int, datetime, int]:
    """Ключ детерминированной сортировки движений по хронологии и бизнес-правилам."""
    type_prio = _TYPE_PRIORITY.get(movement.type, 99)
    created_at = movement.created_at or datetime.max
    mv_id = movement.id if movement.id is not None else 10**9
    return (movement.operation_date, type_prio, created_at, mv_id)


def sort_movements_chronological(
    movements: Iterable[MovementSnapshot],
) -> list[MovementSnapshot]:
    """Сортирует движения в строгом хронологическом порядке учёта."""
    return sorted(movements, key=movement_sort_key)


def batch_fefo_sort_key(
    batch: BatchSnapshot,
) -> tuple[int, date, date, datetime, int]:
    """Ключ сортировки партий по правилу FEFO (сначала с более ранним сроком годности)."""
    has_no_expiry = 1 if batch.expiry_date is None else 0
    expiry = batch.expiry_date or date.max
    created_at = batch.created_at or datetime.min
    return (has_no_expiry, expiry, batch.receipt_date, created_at, batch.id)


def sort_batches_fefo(
    batches: Iterable[BatchSnapshot],
) -> list[BatchSnapshot]:
    """Сортирует партии по правилу FEFO (соответствует индексу idx_batches_fefo)."""
    return sorted(batches, key=batch_fefo_sort_key)


def calculate_batch_stocks(
    batches: Sequence[BatchSnapshot],
    movements: Sequence[MovementSnapshot],
    as_of: date,
    *,
    include_zero: bool = True,
) -> dict[int, BatchStock]:
    """Вычисляет остатки по каждой партии на контрольную дату as_of."""
    # Учитываем только партии, поступившие до или в день as_of
    relevant_batches = {b.id: b for b in batches if b.receipt_date <= as_of}
    batch_quantities: dict[int, Decimal] = dict.fromkeys(relevant_batches, _ZERO_QTY)

    # Фильтруем только активные движения до или в день as_of
    active_movements = [m for m in movements if m.status == "active" and m.operation_date <= as_of]

    for m in active_movements:
        if m.type == "receipt":
            if m.batch_id in batch_quantities:
                batch_quantities[m.batch_id] += m.quantity
        elif m.type == "consume":
            for alloc in m.allocations:
                if alloc.batch_id in batch_quantities:
                    batch_quantities[alloc.batch_id] -= alloc.quantity
        elif m.type == "writeoff":
            if m.batch_id in batch_quantities:
                batch_quantities[m.batch_id] -= m.quantity
        elif m.type == "return":
            if m.batch_id in batch_quantities:
                batch_quantities[m.batch_id] += m.quantity
        elif m.type == "correction":
            if m.batch_id in batch_quantities:
                batch_quantities[m.batch_id] += m.quantity

    result: dict[int, BatchStock] = {}
    for b_id, b in relevant_batches.items():
        qty = batch_quantities[b_id]
        if not include_zero and qty <= _ZERO_QTY:
            continue

        is_expired = b.expiry_date is not None and b.expiry_date < as_of
        if is_expired:
            expired_qty = max(_ZERO_QTY, qty)
            available_qty = _ZERO_QTY
        else:
            expired_qty = _ZERO_QTY
            available_qty = max(_ZERO_QTY, qty)

        result[b_id] = BatchStock(
            batch_id=b.id,
            batch_number=b.batch_number,
            receipt_date=b.receipt_date,
            expiry_date=b.expiry_date,
            unit_price=b.unit_price,
            receipt_doc_number=b.receipt_doc_number,
            current_quantity=qty,
            available_quantity=available_qty,
            expired_quantity=expired_qty,
        )

    return result


def calculate_stock_balance(
    batches: Sequence[BatchSnapshot],
    movements: Sequence[MovementSnapshot],
    as_of: date,
) -> StockBalance:
    """Вычисляет сводный баланс остатков (учётный, доступный, просроченный)."""
    batch_stocks_map = calculate_batch_stocks(
        batches=batches,
        movements=movements,
        as_of=as_of,
        include_zero=True,
    )
    batch_stocks = list(batch_stocks_map.values())

    current_stock = sum((b.current_quantity for b in batch_stocks), _ZERO_QTY)
    available_stock = sum((b.available_quantity for b in batch_stocks), _ZERO_QTY)
    expired_stock = sum((b.expired_quantity for b in batch_stocks), _ZERO_QTY)

    # Ближайшая дата годности среди непросроченных партий с доступным остатком
    valid_expiries = [
        b.expiry_date
        for b in batch_stocks
        if b.available_quantity > _ZERO_QTY and b.expiry_date is not None and b.expiry_date >= as_of
    ]
    nearest_expiry = min(valid_expiries) if valid_expiries else None

    # Сортируем партии в выдаче по FEFO
    sorted_batch_stocks = tuple(
        sorted(
            batch_stocks,
            key=lambda b: (
                1 if b.expiry_date is None else 0,
                b.expiry_date or date.max,
                b.receipt_date,
                b.batch_id,
            ),
        )
    )

    return StockBalance(
        current_stock=current_stock,
        available_stock=available_stock,
        expired_stock=expired_stock,
        nearest_expiry_date=nearest_expiry,
        batches=sorted_batch_stocks,
    )
