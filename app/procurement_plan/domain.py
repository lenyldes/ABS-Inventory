"""Доменные структуры данных для снимка БД и расчёта плана закупок."""

from dataclasses import dataclass
from datetime import date

from app.api.plan_schemas import ExistingOrderSnapshotSchema
from app.forecasting.domain import ProcurementContext
from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.models.catalog import Item, Location


@dataclass(frozen=True)
class PlanItemLocationPair:
    """Исходные данные для пары «товар + объект» в согласованном снимке БД."""

    item: Item
    location: Location
    batches: tuple[BatchSnapshot, ...]
    movements: tuple[MovementSnapshot, ...]
    procurement_context: ProcurementContext
    active_orders: tuple[ExistingOrderSnapshotSchema, ...]


@dataclass(frozen=True)
class PlanDatabaseSnapshot:
    """Согласованный снимок базы данных для расчёта плана повторных закупок."""

    as_of: date
    pairs: tuple[PlanItemLocationPair, ...]
    existing_orders: tuple[ExistingOrderSnapshotSchema, ...]
