"""Маршруты API сводных и детальных остатков склада."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.stock_schemas import (
    BatchStockDetail,
    LocationStockDetail,
    StockSkuResponse,
    StockSummaryItem,
    StockSummaryResponse,
)
from app.core.database import get_db
from app.core.timezone import today_in_moscow
from app.forecasting.consumption import calculate_consumption_metrics
from app.inventory.calculator import calculate_stock_balance
from app.inventory.common_validation import load_history
from app.inventory.exceptions import (
    EntityNotFoundError,
    InvalidPaginationError,
)
from app.inventory.repository import (
    get_item_by_sku,
    get_location_by_code,
)
from app.models.catalog import Item, Location
from app.models.inventory import Batch, Movement

router = APIRouter(prefix="/api/stock", tags=["Stock"])
_ZERO = Decimal("0.000")


@router.get(
    "",
    response_model=StockSummaryResponse,
    summary="Сводный список остатков товаров по объектам",
)
def get_stock_summary(
    location: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    sku: Annotated[str | None, Query()] = None,
    as_of: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query()] = 50,
    offset: Annotated[int, Query()] = 0,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> StockSummaryResponse:
    """Возвращает сводный список остатков (учётный, доступный, просроченный)."""
    if limit < 1 or limit > 100:
        raise InvalidPaginationError(
            "Параметр limit должен быть в диапазоне от 1 до 100",
            details={"limit": limit},
        )
    if offset < 0:
        raise InvalidPaginationError(
            "Параметр offset не может быть отрицательным",
            details={"offset": offset},
        )

    calc_date = as_of or today_in_moscow()

    # Пары (item_id, location_id), по которым есть активные движения или партии
    m_pairs = select(Movement.item_id, Movement.location_id).distinct()
    b_pairs = select(Batch.item_id, Batch.location_id).distinct()
    pairs_sub = m_pairs.union(b_pairs).subquery()

    base_query = (
        select(Item, Location)
        .select_from(pairs_sub)
        .join(Item, Item.id == pairs_sub.c.item_id)
        .join(Location, Location.id == pairs_sub.c.location_id)
    )

    if sku:
        base_query = base_query.where(Item.sku == sku)
    if category:
        base_query = base_query.where(Item.category == category)
    if location:
        base_query = base_query.where(Location.code == location)

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_stmt).scalar_one()

    pairs = list(
        db.execute(
            base_query.order_by(Item.sku.asc(), Location.code.asc()).offset(offset).limit(limit)
        ).all()
    )

    items_list: list[StockSummaryItem] = []
    for item, loc in pairs:
        _, _, b_snaps, m_snaps = load_history(db, item.id, loc.id)
        balance = calculate_stock_balance(b_snaps, m_snaps, as_of=calc_date)
        consumption = calculate_consumption_metrics(
            m_snaps, as_of=calc_date, available_stock=balance.available_stock
        )

        items_list.append(
            StockSummaryItem(
                sku=item.sku,
                name=item.name,
                category=item.category,
                unit=item.unit,
                location=loc.code,
                current_stock=balance.current_stock,
                available_stock=balance.available_stock,
                expired_stock=balance.expired_stock,
                average_daily_consumption=consumption.average_daily_consumption,
                days_of_stock=consumption.days_of_stock,
                nearest_expiry_date=balance.nearest_expiry_date,
            )
        )

    return StockSummaryResponse(
        items=items_list,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{sku}",
    response_model=StockSkuResponse,
    summary="Детализация остатка по конкретному товару и его партиям",
)
def get_stock_by_sku(
    sku: str,
    location: Annotated[str | None, Query()] = None,
    as_of: Annotated[date | None, Query()] = None,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> StockSkuResponse:
    """Возвращает детализацию остатков по объектам и партиям для заданного SKU."""
    item = get_item_by_sku(db, sku)
    if not item:
        raise EntityNotFoundError("Item", sku)

    calc_date = as_of or today_in_moscow()

    if location is not None:
        target_loc = get_location_by_code(db, location)
        if not target_loc:
            raise EntityNotFoundError("Location", location)
        locations_to_check = [target_loc]
    else:
        loc_ids = (
            select(Location.id)
            .join(Movement, Movement.location_id == Location.id)
            .where(Movement.item_id == item.id)
            .union(
                select(Location.id)
                .join(Batch, Batch.location_id == Location.id)
                .where(Batch.item_id == item.id)
            )
        )
        locations_to_check = list(
            db.execute(
                select(Location).where(Location.id.in_(loc_ids)).order_by(Location.code.asc())
            )
            .scalars()
            .all()
        )

    loc_details: list[LocationStockDetail] = []
    for loc in locations_to_check:
        _, _, b_snaps, m_snaps = load_history(db, item.id, loc.id)
        balance = calculate_stock_balance(b_snaps, m_snaps, as_of=calc_date)

        # В детальный список партий включаем партии с ненулевым физическим остатком
        active_batches = [b for b in balance.batches if b.current_quantity > _ZERO]
        batch_items = [
            BatchStockDetail(
                batch_id=b.batch_id,
                batch_number=b.batch_number,
                receipt_date=b.receipt_date,
                expiry_date=b.expiry_date,
                unit_price=b.unit_price,
                quantity=b.current_quantity,
                available_quantity=b.available_quantity,
                receipt_doc_number=b.receipt_doc_number,
            )
            for b in active_batches
        ]

        loc_details.append(
            LocationStockDetail(
                location=loc.code,
                current_stock=balance.current_stock,
                available_stock=balance.available_stock,
                expired_stock=balance.expired_stock,
                batches=batch_items,
            )
        )

    return StockSkuResponse(
        sku=item.sku,
        name=item.name,
        category=item.category,
        unit=item.unit,
        locations=loc_details,
    )
