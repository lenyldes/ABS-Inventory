"""Маршруты API складских движений: регистрация и журнал."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.movement_journal import MovementJournalBuilder
from app.api.movement_schemas import (
    AllocationResponse,
    MovementCreateRequest,
    MovementListResponse,
    MovementResponse,
)
from app.core.database import get_db
from app.inventory.exceptions import (
    EntityNotFoundError,
    InvalidMovementError,
    InvalidPaginationError,
)
from app.inventory.operations import (
    register_consume,
    register_correction,
    register_receipt,
    register_return,
    register_writeoff,
)
from app.inventory.repository import (
    get_item_by_sku,
    get_location_by_code,
)
from app.models.catalog import Item, Location
from app.models.inventory import Movement

router = APIRouter(prefix="/api/movements", tags=["Movements"])


@router.post(
    "",
    response_model=MovementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация нового движения",
)
def create_movement(
    body: MovementCreateRequest,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> MovementResponse:
    """Регистрирует складскую операцию одного из пяти типов."""
    item = get_item_by_sku(db, body.sku)
    if not item:
        raise EntityNotFoundError("Item", body.sku)

    loc = get_location_by_code(db, body.location)
    if not loc:
        raise EntityNotFoundError("Location", body.location)

    m_type = body.type
    if m_type == "receipt":
        res = register_receipt(
            db,
            item=item,
            location=loc,
            operation_date=body.operation_date,
            quantity=body.quantity,
            doc_number=body.doc_number,
            batch_number=body.batch_number or "",
            expiry_date=body.expiry_date,
            unit_price=body.unit_price or 0,  # type: ignore[arg-type]
            purchase_order_id=body.purchase_order_id,
            supplier_id=body.supplier_id,
        )
    elif m_type == "consume":
        res = register_consume(
            db,
            item=item,
            location=loc,
            operation_date=body.operation_date,
            quantity=body.quantity,
            doc_number=body.doc_number,
        )
    elif m_type == "writeoff":
        res = register_writeoff(
            db,
            item=item,
            location=loc,
            operation_date=body.operation_date,
            quantity=body.quantity,
            doc_number=body.doc_number,
            batch_id=body.batch_id or 0,
            reason=body.reason or "",
        )
    elif m_type == "return":
        res = register_return(
            db,
            item=item,
            location=loc,
            operation_date=body.operation_date,
            quantity=body.quantity,
            doc_number=body.doc_number,
            parent_movement_id=body.parent_movement_id or 0,
            parent_allocation_id=body.parent_allocation_id or 0,
            reason=body.reason,
        )
    elif m_type == "correction":
        res = register_correction(
            db,
            item=item,
            location=loc,
            operation_date=body.operation_date,
            quantity=body.quantity,
            doc_number=body.doc_number,
            batch_id=body.batch_id or 0,
            reason=body.reason or "",
        )
    else:
        raise InvalidMovementError(f"Неизвестный тип движения: {m_type}")

    db.commit()

    allocations = [
        AllocationResponse(
            id=a.id,
            batch_id=a.batch_id,
            quantity=a.quantity,
            unit_price=a.unit_price,
        )
        for a in res.allocations
    ]

    return MovementResponse(
        id=res.movement.id,
        operation_date=res.movement.operation_date,
        sku=item.sku,
        location=loc.code,
        type=res.movement.type,
        quantity=res.movement.quantity,
        doc_number=res.movement.doc_number,
        current_stock=res.current_stock,
        available_stock=res.available_stock,
        allocations=allocations,
    )


@router.get(
    "",
    response_model=MovementListResponse,
    summary="Журнал складских движений с фильтрами и предупреждениями",
)
def list_movements(
    sku: Annotated[str | None, Query()] = None,
    location: Annotated[str | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    sort_by: Annotated[str, Query()] = "operation_date",
    sort_order: Annotated[str, Query()] = "desc",
    limit: Annotated[int, Query()] = 50,
    offset: Annotated[int, Query()] = 0,
    db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> MovementListResponse:
    """Возвращает страницу журнала движений с расчётом предупреждений FEFO."""
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
    if sort_by not in ("operation_date", "created_at"):
        raise InvalidPaginationError(
            "Недопустимое поле сортировки: допускается 'operation_date' или 'created_at'",
            details={"sort_by": sort_by},
        )
    if sort_order not in ("asc", "desc"):
        raise InvalidPaginationError(
            "Недопустимый порядок сортировки: допускается 'asc' или 'desc'",
            details={"sort_order": sort_order},
        )
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidMovementError(
            f"Параметр date_from ({date_from.isoformat()}) "
            f"не может быть позже date_to ({date_to.isoformat()})",
            code="INVALID_DATE_RANGE",
            details={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        )

    base_query = (
        select(Movement)
        .join(Item, Movement.item_id == Item.id)
        .join(Location, Movement.location_id == Location.id)
        .where(Movement.status == "active")
    )

    if sku:
        base_query = base_query.where(Item.sku == sku)
    if location:
        base_query = base_query.where(Location.code == location)
    if type:
        base_query = base_query.where(Movement.type == type)
    if date_from:
        base_query = base_query.where(Movement.operation_date >= date_from)
    if date_to:
        base_query = base_query.where(Movement.operation_date <= date_to)

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_stmt).scalar_one()

    if sort_by == "operation_date":
        sort_col = (
            Movement.operation_date.asc() if sort_order == "asc" else Movement.operation_date.desc()
        )
    else:
        sort_col = Movement.created_at.asc() if sort_order == "asc" else Movement.created_at.desc()
    id_col = Movement.id.asc() if sort_order == "asc" else Movement.id.desc()

    items_stmt = (
        base_query.options(
            joinedload(Movement.item),
            joinedload(Movement.location),
            joinedload(Movement.allocations),
        )
        .order_by(sort_col, id_col)
        .offset(offset)
        .limit(limit)
    )
    movements = list(db.execute(items_stmt).unique().scalars().all())

    builder = MovementJournalBuilder(db)
    items_result = [builder.build_item(m) for m in movements]

    return MovementListResponse(
        items=items_result,
        total=total,
        limit=limit,
        offset=offset,
    )
