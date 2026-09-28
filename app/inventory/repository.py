"""Репозиторий складского учёта для работы с PostgreSQL через SQLAlchemy."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload

from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement, MovementAllocation, StockLock
from app.models.procurement import PurchaseOrder


def acquire_stock_lock(session: Session, item_id: int, location_id: int) -> None:
    """Обеспечивает наличие строки stock_locks и берёт SELECT FOR UPDATE на пару."""
    stmt = (
        insert(StockLock)
        .values(item_id=item_id, location_id=location_id)
        .on_conflict_do_nothing(index_elements=["item_id", "location_id"])
    )
    session.execute(stmt)
    session.flush()

    lock_stmt = (
        select(StockLock.id)
        .where(StockLock.item_id == item_id, StockLock.location_id == location_id)
        .with_for_update()
    )
    session.execute(lock_stmt).scalar_one()


def get_item_by_sku(session: Session, sku: str) -> Item | None:
    """Возвращает товар по артикулу SKU."""
    return session.execute(select(Item).where(Item.sku == sku)).scalar_one_or_none()


def get_location_by_code(session: Session, code: str) -> Location | None:
    """Возвращает объект (SPA-филиал) по коду."""
    return session.execute(select(Location).where(Location.code == code)).scalar_one_or_none()


def get_supplier_by_id(session: Session, supplier_id: str) -> Supplier | None:
    """Возвращает поставщика по коду supplier_id."""
    return session.execute(
        select(Supplier).where(Supplier.supplier_id == supplier_id)
    ).scalar_one_or_none()


def is_doc_number_active(session: Session, location_id: int, doc_number: str) -> bool:
    """Проверяет, зарегистрирован ли уже активный документ с таким номером на объекте."""
    stmt = select(Movement.id).where(
        Movement.location_id == location_id,
        Movement.doc_number == doc_number,
        Movement.status == "active",
    )
    return session.execute(stmt).scalar_one_or_none() is not None


def get_batches(session: Session, item_id: int, location_id: int) -> list[Batch]:
    """Возвращает все партии товара на объекте."""
    stmt = (
        select(Batch)
        .where(Batch.item_id == item_id, Batch.location_id == location_id)
        .order_by(Batch.id.asc())
    )
    return list(session.execute(stmt).scalars().all())


def get_movements_with_allocations(
    session: Session,
    item_id: int,
    location_id: int,
) -> list[Movement]:
    """Возвращает движения товара на объекте с загруженными строками распределений."""
    stmt = (
        select(Movement)
        .options(joinedload(Movement.allocations))
        .where(Movement.item_id == item_id, Movement.location_id == location_id)
        .order_by(Movement.operation_date.asc(), Movement.id.asc())
    )
    return list(session.execute(stmt).unique().scalars().all())


def get_purchase_order_for_update(session: Session, po_id: int) -> PurchaseOrder | None:
    """Возвращает заказ поставщику с блокировкой строки FOR UPDATE."""
    stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def get_movement_by_id(session: Session, movement_id: int) -> Movement | None:
    """Возвращает движение по идентификатору."""
    stmt = (
        select(Movement).options(joinedload(Movement.allocations)).where(Movement.id == movement_id)
    )
    return session.execute(stmt).unique().scalar_one_or_none()


def get_allocation_by_id(session: Session, allocation_id: int) -> MovementAllocation | None:
    """Возвращает строку распределения по идентификатору."""
    stmt = select(MovementAllocation).where(MovementAllocation.id == allocation_id)
    return session.execute(stmt).scalar_one_or_none()


def create_batch(
    session: Session,
    *,
    item_id: int,
    location_id: int,
    batch_number: str,
    receipt_date: date,
    expiry_date: date | None,
    unit_price: Decimal,
    receipt_doc_number: str,
) -> Batch:
    """Создаёт новую учётную партию."""
    batch = Batch(
        item_id=item_id,
        location_id=location_id,
        batch_number=batch_number,
        receipt_date=receipt_date,
        expiry_date=expiry_date,
        unit_price=unit_price,
        receipt_doc_number=receipt_doc_number,
    )
    session.add(batch)
    session.flush()
    return batch


def create_movement(
    session: Session,
    *,
    operation_date: date,
    item_id: int,
    location_id: int,
    type: str,
    quantity: Decimal,
    doc_number: str,
    batch_id: int | None = None,
    reason: str | None = None,
    parent_movement_id: int | None = None,
    parent_allocation_id: int | None = None,
    purchase_order_id: int | None = None,
    supplier_id: int | None = None,
) -> Movement:
    """Создаёт запись складского движения."""
    mv = Movement(
        operation_date=operation_date,
        item_id=item_id,
        location_id=location_id,
        type=type,
        quantity=quantity,
        doc_number=doc_number,
        batch_id=batch_id,
        reason=reason,
        parent_movement_id=parent_movement_id,
        parent_allocation_id=parent_allocation_id,
        purchase_order_id=purchase_order_id,
        supplier_id=supplier_id,
        status="active",
        current_version=1,
    )
    session.add(mv)
    session.flush()
    return mv


def create_allocations(
    session: Session,
    movement_id: int,
    allocations_data: list[AllocationSnapshot],
) -> list[MovementAllocation]:
    """Создаёт строки распределения расхода по партиям."""
    allocs = [
        MovementAllocation(
            movement_id=movement_id,
            batch_id=a.batch_id,
            quantity=a.quantity,
            unit_price=a.unit_price,
        )
        for a in allocations_data
    ]
    session.add_all(allocs)
    session.flush()
    return allocs


def batch_to_snapshot(batch: Batch) -> BatchSnapshot:
    """Конвертирует модель Batch в доменный снимок BatchSnapshot."""
    return BatchSnapshot(
        id=batch.id,
        item_id=batch.item_id,
        location_id=batch.location_id,
        batch_number=batch.batch_number,
        receipt_date=batch.receipt_date,
        expiry_date=batch.expiry_date,
        unit_price=batch.unit_price,
        receipt_doc_number=batch.receipt_doc_number,
        created_at=batch.created_at,
    )


def movement_to_snapshot(movement: Movement) -> MovementSnapshot:
    """Конвертирует модель Movement в доменный снимок MovementSnapshot."""
    allocs = tuple(
        AllocationSnapshot(
            id=a.id,
            movement_id=a.movement_id,
            batch_id=a.batch_id,
            quantity=a.quantity,
            unit_price=a.unit_price,
        )
        for a in (movement.allocations or [])
    )
    return MovementSnapshot(
        id=movement.id,
        operation_date=movement.operation_date,
        created_at=movement.created_at,
        item_id=movement.item_id,
        location_id=movement.location_id,
        type=movement.type,
        quantity=movement.quantity,
        doc_number=movement.doc_number,
        batch_id=movement.batch_id,
        reason=movement.reason,
        parent_movement_id=movement.parent_movement_id,
        parent_allocation_id=movement.parent_allocation_id,
        purchase_order_id=movement.purchase_order_id,
        supplier_id=movement.supplier_id,
        status=movement.status,
        allocations=allocs,
    )
