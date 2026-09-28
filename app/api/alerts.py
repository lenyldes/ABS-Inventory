"""Маршруты API предупреждений по рискам запасов и ограничениям данных."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.alerts_schemas import (
    AlertLevel,
    AlertResponseItem,
    AlertsListResponse,
    AlertType,
)
from app.core.database import get_db
from app.core.timezone import today_in_moscow
from app.forecasting.alerts import calculate_item_alerts
from app.forecasting.domain import AlertItem
from app.forecasting.procurement_repository import load_procurement_context
from app.inventory.calculator import calculate_stock_balance
from app.inventory.common_validation import load_history
from app.models.catalog import Item, Location
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

_LEVEL_ORDER = {
    AlertLevel.critical.value: 0,
    AlertLevel.warning.value: 1,
    AlertLevel.info.value: 2,
}


def _validate_alert_query_params(
    horizon_days: int | None,
    shelf_life_days_threshold: int,
    no_movement_days_threshold: int,
    limit: int,
    offset: int,
) -> None:
    """Проверяет корректность параметров фильтрации и пагинации."""
    if horizon_days is not None and horizon_days < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр horizon_days должен быть >= 1",
        )
    if shelf_life_days_threshold < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр shelf_life_days_threshold должен быть >= 1",
        )
    if no_movement_days_threshold < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр no_movement_days_threshold должен быть >= 1",
        )
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр limit должен быть в диапазоне от 1 до 100",
        )
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр offset не может быть отрицательным",
        )


def _alert_sort_key(alert: AlertItem) -> tuple[int, str, str, str, str]:
    """Формирует ключ для детерминированной стабильной сортировки предупреждений."""
    return (
        _LEVEL_ORDER.get(alert.level, 99),
        alert.sku,
        alert.location,
        alert.type,
        alert.id,
    )


@router.get(
    "",
    response_model=AlertsListResponse,
    summary="Получение списка предупреждений по запасам и рискам",
)
def get_alerts(
    location: Annotated[str | None, Query(description="Фильтр по коду объекта")] = None,
    sku: Annotated[str | None, Query(description="Фильтр по артикулу товара")] = None,
    type: Annotated[AlertType | None, Query(description="Фильтр по типу предупреждения")] = None,
    level: Annotated[AlertLevel | None, Query(description="Фильтр по уровню критичности")] = None,
    as_of: Annotated[date | None, Query(description="Дата среза (по умолчанию сегодня)")] = None,
    horizon_days: Annotated[
        int | None, Query(description="Явный горизонт прогноза в днях (>= 1)")
    ] = None,
    shelf_life_days_threshold: Annotated[
        int, Query(description="Порог приближения срока годности в днях (>= 1)")
    ] = 30,
    no_movement_days_threshold: Annotated[
        int, Query(description="Порог отсутствия движения в днях (>= 1)")
    ] = 90,
    limit: Annotated[int, Query(description="Лимит записей (от 1 до 100)")] = 50,
    offset: Annotated[int, Query(description="Смещение (>= 0)")] = 0,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AlertsListResponse:
    """Вычисляет и возвращает список предупреждений с фильтрацией, сортировкой и пагинацией."""
    _validate_alert_query_params(
        horizon_days=horizon_days,
        shelf_life_days_threshold=shelf_life_days_threshold,
        no_movement_days_threshold=no_movement_days_threshold,
        limit=limit,
        offset=offset,
    )

    calc_as_of = as_of or today_in_moscow()

    m_pairs = select(Movement.item_id, Movement.location_id).distinct()
    b_pairs = select(Batch.item_id, Batch.location_id).distinct()
    po_pairs = select(PurchaseOrder.item_id, PurchaseOrder.location_id).distinct()
    pairs_sub = m_pairs.union(b_pairs, po_pairs).subquery()

    base_query = (
        select(Item, Location)
        .select_from(pairs_sub)
        .join(Item, Item.id == pairs_sub.c.item_id)
        .join(Location, Location.id == pairs_sub.c.location_id)
    )

    if sku:
        base_query = base_query.where(Item.sku == sku)
    if location:
        base_query = base_query.where(Location.code == location)

    pairs = list(db.execute(base_query.order_by(Item.sku.asc(), Location.code.asc())).all())

    all_alerts: list[AlertItem] = []
    for item, loc in pairs:
        _, _, b_snaps, m_snaps = load_history(db, item.id, loc.id)
        procurement_ctx = load_procurement_context(db, item.id, loc.id, calc_as_of)
        balance = calculate_stock_balance(batches=b_snaps, movements=m_snaps, as_of=calc_as_of)

        item_alerts = calculate_item_alerts(
            sku=item.sku,
            location=loc.code,
            as_of=calc_as_of,
            stock_balance=balance,
            movements=m_snaps,
            procurement=procurement_ctx,
            horizon_days=horizon_days,
            shelf_life_days_threshold=shelf_life_days_threshold,
            no_movement_days_threshold=no_movement_days_threshold,
            batches=b_snaps,
        )
        all_alerts.extend(item_alerts)

    if type is not None:
        target_type = type.value if hasattr(type, "value") else str(type)
        all_alerts = [a for a in all_alerts if a.type == target_type]

    if level is not None:
        target_level = level.value if hasattr(level, "value") else str(level)
        all_alerts = [a for a in all_alerts if a.level == target_level]

    all_alerts.sort(key=_alert_sort_key)

    total = len(all_alerts)
    paged_alerts = all_alerts[offset : offset + limit]

    items = [
        AlertResponseItem(
            id=a.id,
            type=a.type,
            level=a.level,
            sku=a.sku,
            location=a.location,
            batch_id=a.batch_id,
            message=a.message,
            metrics=a.metrics,
            as_of=a.as_of,
        )
        for a in paged_alerts
    ]

    return AlertsListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
