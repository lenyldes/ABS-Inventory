"""Доменный модуль складского учёта, партий и движений."""

from app.inventory.calculator import (
    batch_fefo_sort_key,
    calculate_batch_stocks,
    calculate_stock_balance,
    movement_sort_key,
    sort_batches_fefo,
    sort_movements_chronological,
)
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    BatchStock,
    MovementSnapshot,
    MovementWarning,
    StockBalance,
)
from app.inventory.exceptions import (
    DocumentDuplicateError,
    EntityNotFoundError,
    ExcessReturnError,
    HistoricalSufficiencyError,
    InsufficientStockError,
    InvalidMovementError,
    InventoryError,
)
from app.inventory.fefo import allocate_fefo, detect_fefo_deviation
from app.inventory.history import validate_history_sufficiency
from app.inventory.operations import (
    MovementExecutionResult,
    register_consume,
    register_correction,
    register_receipt,
    register_return,
    register_writeoff,
)

__all__ = [
    "AllocationSnapshot",
    "BatchSnapshot",
    "BatchStock",
    "DocumentDuplicateError",
    "EntityNotFoundError",
    "ExcessReturnError",
    "HistoricalSufficiencyError",
    "InsufficientStockError",
    "InvalidMovementError",
    "InventoryError",
    "MovementExecutionResult",
    "MovementSnapshot",
    "MovementWarning",
    "StockBalance",
    "allocate_fefo",
    "batch_fefo_sort_key",
    "calculate_batch_stocks",
    "calculate_stock_balance",
    "detect_fefo_deviation",
    "movement_sort_key",
    "register_consume",
    "register_correction",
    "register_receipt",
    "register_return",
    "register_writeoff",
    "sort_batches_fefo",
    "sort_movements_chronological",
    "validate_history_sufficiency",
]
