"""Проверка отсутствия внешних ссылок перед пересборкой демонстрационных данных."""

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.demo_data.catalog import (
    DEMO_CONDITIONS,
    DEMO_ITEM_SKUS,
    DEMO_LOCATION_CODES,
    DEMO_SUPPLIER_IDS,
)
from app.demo_data.inspection import DemoDataError
from app.demo_data.movements import (
    DEMO_BATCH_NUMBERS,
    DEMO_MOVEMENT_DOC_NUMBERS,
)
from app.demo_data.orders import DEMO_ORDER_DOC_NUMBERS
from app.models.amendments import AmendmentEntry
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement, MovementAllocation
from app.models.procurement import PurchaseOrder, SupplierCondition


@dataclass(frozen=True)
class DemoEntityIds:
    """Идентификаторы сущностей существующего демонстрационного набора в БД."""

    item_ids: set[int]
    location_ids: set[int]
    supplier_ids: set[int]
    batch_ids: set[int]
    movement_ids: set[int]
    order_ids: set[int]


def resolve_demo_entity_ids(session: Session) -> DemoEntityIds:
    """Находит в базе данных ID всех сущностей, соответствующих точным ключам демонабора."""
    item_ids = {id_ for (id_,) in session.query(Item.id).filter(Item.sku.in_(DEMO_ITEM_SKUS)).all()}
    location_ids = {
        id_
        for (id_,) in session.query(Location.id)
        .filter(Location.code.in_(DEMO_LOCATION_CODES))
        .all()
    }
    supplier_ids = {
        id_
        for (id_,) in session.query(Supplier.id)
        .filter(Supplier.supplier_id.in_(DEMO_SUPPLIER_IDS))
        .all()
    }
    batch_ids = {
        id_
        for (id_,) in session.query(Batch.id)
        .filter(Batch.batch_number.in_(DEMO_BATCH_NUMBERS))
        .all()
    }
    movement_ids = {
        id_
        for (id_,) in session.query(Movement.id)
        .filter(Movement.doc_number.in_(DEMO_MOVEMENT_DOC_NUMBERS))
        .all()
    }
    order_ids = {
        id_
        for (id_,) in session.query(PurchaseOrder.id)
        .filter(PurchaseOrder.doc_number.in_(DEMO_ORDER_DOC_NUMBERS))
        .all()
    }
    return DemoEntityIds(
        item_ids=item_ids,
        location_ids=location_ids,
        supplier_ids=supplier_ids,
        batch_ids=batch_ids,
        movement_ids=movement_ids,
        order_ids=order_ids,
    )


def check_external_references(session: Session, demo_ids: DemoEntityIds) -> None:
    """Проверяет отсутствие сторонних ссылок на демонстрационные сущности.

    При обнаружении любой внешней связи вызывает DemoDataError до удаления данных.
    """
    # 1. Чужие складские движения на демотовар, объект, поставщика, партию или заказ
    m_conds = []
    if demo_ids.item_ids:
        m_conds.append(Movement.item_id.in_(demo_ids.item_ids))
    if demo_ids.location_ids:
        m_conds.append(Movement.location_id.in_(demo_ids.location_ids))
    if demo_ids.supplier_ids:
        m_conds.append(Movement.supplier_id.in_(demo_ids.supplier_ids))
    if demo_ids.batch_ids:
        m_conds.append(Movement.batch_id.in_(demo_ids.batch_ids))
    if demo_ids.order_ids:
        m_conds.append(Movement.purchase_order_id.in_(demo_ids.order_ids))

    if m_conds:
        query = session.query(Movement).filter(or_(*m_conds))
        if demo_ids.movement_ids:
            query = query.filter(~Movement.id.in_(demo_ids.movement_ids))
        foreign_m = query.first()
        if foreign_m is not None:
            raise DemoDataError(
                f"Обнаружено стороннее складское движение '{foreign_m.doc_number}', "
                "ссылающееся на демонстрационные данные. Пересборка отменена."
            )

    # 2. Дочерние складские движения на демодвижения
    if demo_ids.movement_ids:
        child_m = (
            session.query(Movement)
            .filter(
                Movement.parent_movement_id.in_(demo_ids.movement_ids),
                ~Movement.id.in_(demo_ids.movement_ids),
            )
            .first()
        )
        if child_m is not None:
            raise DemoDataError(
                f"Обнаружено дочернее движение '{child_m.doc_number}', "
                "ссылающееся на демонстрационное движение. Пересборка отменена."
            )

        demo_alloc_ids = {
            id_
            for (id_,) in session.query(MovementAllocation.id)
            .filter(MovementAllocation.movement_id.in_(demo_ids.movement_ids))
            .all()
        }
        if demo_alloc_ids:
            child_alloc_m = (
                session.query(Movement)
                .filter(
                    Movement.parent_allocation_id.in_(demo_alloc_ids),
                    ~Movement.id.in_(demo_ids.movement_ids),
                )
                .first()
            )
            if child_alloc_m is not None:
                raise DemoDataError(
                    f"Обнаружено движение '{child_alloc_m.doc_number}', "
                    "ссылающееся на распределение демодвижения. Пересборка отменена."
                )

    # 3. Чужие распределения на демопартию
    if demo_ids.batch_ids:
        query_alloc = session.query(MovementAllocation).filter(
            MovementAllocation.batch_id.in_(demo_ids.batch_ids)
        )
        if demo_ids.movement_ids:
            query_alloc = query_alloc.filter(
                ~MovementAllocation.movement_id.in_(demo_ids.movement_ids)
            )
        foreign_alloc = query_alloc.first()
        if foreign_alloc is not None:
            raise DemoDataError(
                "Обнаружено стороннее распределение движения, "
                f"ссылающееся на демонстрационную партию ID {foreign_alloc.batch_id}. "
                "Пересборка отменена."
            )

    # 4. Чужие партии на демотовар или демообъект
    b_conds = []
    if demo_ids.item_ids:
        b_conds.append(Batch.item_id.in_(demo_ids.item_ids))
    if demo_ids.location_ids:
        b_conds.append(Batch.location_id.in_(demo_ids.location_ids))
    if b_conds:
        query_b = session.query(Batch).filter(or_(*b_conds))
        if demo_ids.batch_ids:
            query_b = query_b.filter(~Batch.id.in_(demo_ids.batch_ids))
        foreign_batch = query_b.first()
        if foreign_batch is not None:
            raise DemoDataError(
                f"Обнаружена сторонняя партия '{foreign_batch.batch_number}', "
                "ссылающаяся на демонстрационные данные. Пересборка отменена."
            )

    # 5. Чужие заказы поставщикам на демотовар, объект или поставщика
    po_conds = []
    if demo_ids.item_ids:
        po_conds.append(PurchaseOrder.item_id.in_(demo_ids.item_ids))
    if demo_ids.location_ids:
        po_conds.append(PurchaseOrder.location_id.in_(demo_ids.location_ids))
    if demo_ids.supplier_ids:
        po_conds.append(PurchaseOrder.supplier_id.in_(demo_ids.supplier_ids))
    if po_conds:
        query_po = session.query(PurchaseOrder).filter(or_(*po_conds))
        if demo_ids.order_ids:
            query_po = query_po.filter(~PurchaseOrder.id.in_(demo_ids.order_ids))
        foreign_po = query_po.first()
        if foreign_po is not None:
            raise DemoDataError(
                f"Обнаружен сторонний заказ поставщику '{foreign_po.doc_number}', "
                "ссылающийся на демонстрационные данные. Пересборка отменена."
            )

    # 6. Чужие закупочные условия на демотовар или поставщика
    cond_filters = []
    if demo_ids.item_ids:
        cond_filters.append(SupplierCondition.item_id.in_(demo_ids.item_ids))
    if demo_ids.supplier_ids:
        cond_filters.append(SupplierCondition.supplier_id.in_(demo_ids.supplier_ids))
    if cond_filters:
        sku_to_id = dict(
            session.query(Item.sku, Item.id).filter(Item.sku.in_(DEMO_ITEM_SKUS)).all()
        )
        sup_code_to_id = dict(
            session.query(Supplier.supplier_id, Supplier.id)
            .filter(Supplier.supplier_id.in_(DEMO_SUPPLIER_IDS))
            .all()
        )
        valid_pairs = {
            (sku_to_id[c["item_sku"]], sup_code_to_id[c["supplier_id"]])
            for c in DEMO_CONDITIONS
            if c["item_sku"] in sku_to_id and c["supplier_id"] in sup_code_to_id
        }
        for cond in session.query(SupplierCondition).filter(or_(*cond_filters)).all():
            if (cond.item_id, cond.supplier_id) not in valid_pairs:
                raise DemoDataError(
                    f"Обнаружено стороннее закупочное условие (товар ID {cond.item_id}, "
                    f"поставщик ID {cond.supplier_id}), ссылающееся на демонстрационные данные. "
                    "Пересборка отменена."
                )

    # 7. Строки исправлений на демодвижения
    if demo_ids.movement_ids:
        amendment = (
            session.query(AmendmentEntry)
            .filter(AmendmentEntry.movement_id.in_(demo_ids.movement_ids))
            .first()
        )
        if amendment is not None:
            raise DemoDataError(
                f"Обнаружена строка исправления (AmendmentEntry ID {amendment.id}) "
                "для демонстрационного движения. Пересборка отменена."
            )
