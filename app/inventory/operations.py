"""Единый фасад регистрации складских операций."""

from app.inventory.adjustments import (
    register_correction,
    register_return,
    register_writeoff,
)
from app.inventory.common_validation import MovementExecutionResult
from app.inventory.receipt_consume import (
    register_consume,
    register_receipt,
)

__all__ = [
    "MovementExecutionResult",
    "register_consume",
    "register_correction",
    "register_receipt",
    "register_return",
    "register_writeoff",
]
