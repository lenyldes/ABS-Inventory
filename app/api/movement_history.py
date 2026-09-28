"""Маршруты API аудита и истории версий складских движений."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.inventory.versions import build_movement_snapshot, get_movement_history_data

router = APIRouter(prefix="/api/movements", tags=["Movements"])


class MovementVersionItem(BaseModel):
    """Строка версии в истории движения."""

    version_num: int
    created_at: datetime
    action: str
    reason: str
    snapshot: dict[str, Any]
    changes: dict[str, Any]


class MovementHistoryResponse(BaseModel):
    """Ответ с полной историей версий и текущим состоянием движения."""

    movement_id: int
    is_cancelled: bool
    current_state: dict[str, Any]
    versions: list[MovementVersionItem]


@router.get(
    "/{id}/history",
    response_model=MovementHistoryResponse,
    summary="Аудит изменений и версий складского движения",
)
def get_movement_history(
    id: int,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> MovementHistoryResponse:
    """Возвращает историю версий складского движения со снимками и изменениями."""
    movement, version_items = get_movement_history_data(db, id)
    current_state = build_movement_snapshot(movement)
    return MovementHistoryResponse(
        movement_id=movement.id,
        is_cancelled=movement.status == "cancelled",
        current_state=current_state,
        versions=[MovementVersionItem(**v) for v in version_items],
    )
