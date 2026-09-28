"""Pydantic-схемы для эндпоинта предупреждений и рисков запасов."""

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class AlertType(StrEnum):
    """Типы предупреждений по запасам и рискам."""

    stockout = "stockout"
    potential_stockout = "potential_stockout"
    expiring_soon = "expiring_soon"
    expired = "expired"
    no_movement = "no_movement"
    writeoff_risk = "writeoff_risk"
    incomplete_history = "incomplete_history"


class AlertLevel(StrEnum):
    """Уровни критичности предупреждений."""

    critical = "critical"
    warning = "warning"
    info = "info"


class AlertResponseItem(BaseModel):
    """Элемент списка предупреждений в ответе API."""

    id: str
    type: str
    level: str
    sku: str
    location: str
    batch_id: int | None = None
    message: str
    metrics: dict[str, Any]
    as_of: date

    model_config = ConfigDict(from_attributes=True)


class AlertsListResponse(BaseModel):
    """Формат ответа списка предупреждений с пагинацией."""

    items: list[AlertResponseItem]
    total: int
    limit: int
    offset: int
