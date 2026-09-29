"""Изолированная пересборка демонстрационного набора данных."""

from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.demo_data.replacement_checks import (
    DemoEntityIds,
    check_external_references,
    resolve_demo_entity_ids,
)
from app.models.amendments import MovementVersion
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement, MovementAllocation, StockLock
from app.models.procurement import PurchaseOrder, SupplierCondition


def delete_demo_data(session: Session, demo_ids: DemoEntityIds) -> None:
    """Удаляет собственные записи демонабора в обратном порядке ограничений FK."""
    # 1. Версии складских движений
    if demo_ids.movement_ids:
        session.query(MovementVersion).filter(
            MovementVersion.movement_id.in_(demo_ids.movement_ids)
        ).delete(synchronize_session=False)

    # 2. Распределения складских движений
    if demo_ids.movement_ids:
        session.query(MovementAllocation).filter(
            MovementAllocation.movement_id.in_(demo_ids.movement_ids)
        ).delete(synchronize_session=False)

    # 3. Складские движения
    if demo_ids.movement_ids:
        session.query(Movement).filter(Movement.id.in_(demo_ids.movement_ids)).delete(
            synchronize_session=False
        )

    # 4. Учётные партии
    if demo_ids.batch_ids:
        session.query(Batch).filter(Batch.id.in_(demo_ids.batch_ids)).delete(
            synchronize_session=False
        )

    # 5. Ожидаемые заказы поставщикам
    if demo_ids.order_ids:
        session.query(PurchaseOrder).filter(PurchaseOrder.id.in_(demo_ids.order_ids)).delete(
            synchronize_session=False
        )

    # 6. Блокировки остатков (StockLock)
    lock_conds = []
    if demo_ids.item_ids:
        lock_conds.append(StockLock.item_id.in_(demo_ids.item_ids))
    if demo_ids.location_ids:
        lock_conds.append(StockLock.location_id.in_(demo_ids.location_ids))
    if lock_conds:
        session.query(StockLock).filter(or_(*lock_conds)).delete(synchronize_session=False)

    # 7. Закупочные условия
    cond_conds = []
    if demo_ids.item_ids:
        cond_conds.append(SupplierCondition.item_id.in_(demo_ids.item_ids))
    if demo_ids.supplier_ids:
        cond_conds.append(SupplierCondition.supplier_id.in_(demo_ids.supplier_ids))
    if cond_conds:
        session.query(SupplierCondition).filter(or_(*cond_conds)).delete(synchronize_session=False)

    # 8. Номенклатура (Item)
    if demo_ids.item_ids:
        session.query(Item).filter(Item.id.in_(demo_ids.item_ids)).delete(synchronize_session=False)

    # 9. Поставщики (Supplier)
    if demo_ids.supplier_ids:
        session.query(Supplier).filter(Supplier.id.in_(demo_ids.supplier_ids)).delete(
            synchronize_session=False
        )

    # 10. SPA-объекты (Location)
    if demo_ids.location_ids:
        session.query(Location).filter(Location.id.in_(demo_ids.location_ids)).delete(
            synchronize_session=False
        )

    session.flush()
    session.expire_all()


def replace_demo_data(session: Session, as_of: date) -> dict[str, int]:
    """Изолированно заменяет демонстрационный набор данных в одной транзакции.

    Проверяет отсутствие сторонних ссылок, удаляет собственные сущности
    демонабора и загружает обновленный набор на новую контрольную дату.
    При любой ошибке изменения полностью откатываются.
    """
    from app.demo_data.loader import load_demo_data

    try:
        demo_ids = resolve_demo_entity_ids(session)
        check_external_references(session, demo_ids)
        delete_demo_data(session, demo_ids)
        stats = load_demo_data(session, as_of)
        return stats
    except Exception:
        session.rollback()
        raise
