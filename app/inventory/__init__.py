"""Доменный модуль складского учёта, партий и движений."""

from app.inventory.amendments_domain import (
    AllocationBatchChange,
    AllocationQuantityChange,
    AmendmentBlocker,
    AmendmentOperation,
    SimulationResult,
    StockImpact,
)
from app.inventory.amendments_service import simulate_amendment_set
from app.inventory.amendments_simulation import apply_amendments_to_snapshots
from app.inventory.amendments_validation import validate_projected_history
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
    AmendmentValidationError,
    DocumentDuplicateError,
    EntityNotFoundError,
    ExcessReturnError,
    HistoricalSufficiencyError,
    InsufficientStockError,
    InvalidMovementError,
    InvalidPaginationError,
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
    "AllocationBatchChange",
    "AllocationQuantityChange",
    "AllocationSnapshot",
    "AmendmentBlocker",
    "AmendmentOperation",
    "AmendmentValidationError",
    "BatchSnapshot",
    "BatchStock",
    "DocumentDuplicateError",
    "EntityNotFoundError",
    "ExcessReturnError",
    "HistoricalSufficiencyError",
    "InsufficientStockError",
    "InvalidMovementError",
    "InvalidPaginationError",
    "InventoryError",
    "MovementExecutionResult",
    "MovementSnapshot",
    "MovementWarning",
    "SimulationResult",
    "StockBalance",
    "StockImpact",
    "allocate_fefo",
    "apply_amendments_to_snapshots",
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
    "simulate_amendment_set",
    "sort_batches_fefo",
    "sort_movements_chronological",
    "validate_history_sufficiency",
    "validate_projected_history",
]
