"""Загрузчик демонстрационного набора данных в базу данных."""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.demo_data.catalog import (
    DEMO_CONDITIONS,
    DEMO_ITEMS,
    DEMO_LOCATIONS,
    DEMO_SUPPLIERS,
)
from app.demo_data.inspection import (
    DemoDataError,
    detect_demo_as_of,
    get_existing_demo_keys,
    verify_demo_keys,
)
from app.demo_data.movements import (
    DEMO_BASE_RECEIPT_DOC,
    DEMO_BATCH_NUMBERS,
    DEMO_MOVEMENTS,
)
from app.demo_data.orders import DEMO_ORDERS
from app.inventory.operations import register_consume, register_receipt
from app.models.catalog import Item, Location, Supplier
from app.models.procurement import PurchaseOrder, SupplierCondition

logger = logging.getLogger(__name__)


def load_demo_data(session: Session, as_of: date) -> dict[str, int]:
    """Загружает полный демонстрационный набор данных в одной транзакции.

    Создает справочники (объекты, поставщики, номенклатуру) и закупочные условия,
    хронологически проводит складские движения через штатные сервисные операции
    (с формированием партий, FEFO-распределений и версий), после чего добавляет
    ожидаемые заказы поставщикам.

    При любой ошибке транзакция полностью откатывается.
    """
    try:
        # 1. Загрузка объектов (SPA-филиалов)
        locations_by_code: dict[str, Location] = {}
        for loc_def in DEMO_LOCATIONS:
            loc = session.query(Location).filter(Location.code == loc_def["code"]).first()
            if loc is None:
                loc = Location(code=loc_def["code"], name=loc_def["name"])
                session.add(loc)
            locations_by_code[loc_def["code"]] = loc

        # 2. Загрузка поставщиков
        suppliers_by_id: dict[str, Supplier] = {}
        for sup_def in DEMO_SUPPLIERS:
            sup = (
                session.query(Supplier)
                .filter(Supplier.supplier_id == sup_def["supplier_id"])
                .first()
            )
            if sup is None:
                sup = Supplier(
                    supplier_id=sup_def["supplier_id"],
                    name=sup_def["name"],
                )
                session.add(sup)
            suppliers_by_id[sup_def["supplier_id"]] = sup

        # 3. Загрузка товаров
        items_by_sku: dict[str, Item] = {}
        for item_def in DEMO_ITEMS:
            item = session.query(Item).filter(Item.sku == item_def["sku"]).first()
            if item is None:
                item = Item(
                    sku=item_def["sku"],
                    name=item_def["name"],
                    category=item_def["category"],
                    unit=item_def["unit"],
                )
                session.add(item)
            items_by_sku[item_def["sku"]] = item

        session.flush()

        # 4. Загрузка закупочных условий
        for cond_def in DEMO_CONDITIONS:
            item = items_by_sku[cond_def["item_sku"]]
            supplier = suppliers_by_id[cond_def["supplier_id"]]
            cond = (
                session.query(SupplierCondition)
                .filter(
                    SupplierCondition.item_id == item.id,
                    SupplierCondition.supplier_id == supplier.id,
                )
                .first()
            )
            if cond is None:
                session.add(
                    SupplierCondition(
                        item_id=item.id,
                        supplier_id=supplier.id,
                        lead_time_days=cond_def["lead_time_days"],
                        package_size=cond_def["package_size"],
                        min_order_qty=cond_def["min_order_qty"],
                        estimated_price=cond_def["estimated_price"],
                        is_primary=cond_def["is_primary"],
                    )
                )

        session.flush()

        # 5. Хронологическое проведение складских движений
        sorted_movements = sorted(
            DEMO_MOVEMENTS,
            key=lambda m: (
                m.resolve_date(as_of),
                0 if m.movement_type == "receipt" else 1,
                m.doc_number,
            ),
        )

        for m in sorted_movements:
            item = items_by_sku[m.sku]
            location = locations_by_code[m.location_code]
            op_date = m.resolve_date(as_of)

            if m.movement_type == "receipt":
                exp_date = m.resolve_expiry_date(as_of)
                assert m.batch_number is not None
                assert m.unit_price is not None
                register_receipt(
                    session,
                    item=item,
                    location=location,
                    operation_date=op_date,
                    quantity=m.quantity,
                    doc_number=m.doc_number,
                    batch_number=m.batch_number,
                    expiry_date=exp_date,
                    unit_price=m.unit_price,
                    supplier_id=m.supplier_id,
                )
            elif m.movement_type == "consume":
                register_consume(
                    session,
                    item=item,
                    location=location,
                    operation_date=op_date,
                    quantity=m.quantity,
                    doc_number=m.doc_number,
                )

        # 6. Создание ожидаемых заказов поставщикам
        for o in DEMO_ORDERS:
            item = items_by_sku[o.sku]
            location = locations_by_code[o.location_code]
            supplier = suppliers_by_id[o.supplier_id]
            expected_date = o.resolve_expected_date(as_of)

            existing_order = (
                session.query(PurchaseOrder)
                .filter(
                    PurchaseOrder.location_id == location.id,
                    PurchaseOrder.doc_number == o.doc_number,
                )
                .first()
            )
            if existing_order is None:
                session.add(
                    PurchaseOrder(
                        item_id=item.id,
                        location_id=location.id,
                        supplier_id=supplier.id,
                        doc_number=o.doc_number,
                        expected_date=expected_date,
                        expected_qty=o.expected_qty,
                        received_qty=o.received_qty,
                        pending_qty=o.pending_qty,
                        unit_price=o.unit_price,
                        status=o.status,
                    )
                )

        session.commit()

        stats = {
            "locations": len(DEMO_LOCATIONS),
            "suppliers": len(DEMO_SUPPLIERS),
            "items": len(DEMO_ITEMS),
            "supplier_conditions": len(DEMO_CONDITIONS),
            "movements": len(DEMO_MOVEMENTS),
            "batches": len(DEMO_BATCH_NUMBERS),
            "orders": len(DEMO_ORDERS),
        }
        return stats

    except Exception:
        session.rollback()
        raise


def prepare_demo_data(
    session: Session,
    as_of: date,
    replace: bool = False,
) -> tuple[str, dict[str, int]]:
    """Готовит или подтверждает демонстрационный набор данных в одной транзакции.

    - Если демонстрационных данных в БД нет, загружает их (режим 'created').
    - Если данные уже есть:
      - Проверяет опорное движение и сверяет полный перечень ключей.
      - При совпадении as_of: безопасный повтор без изменений (режим 'idempotent').
      - При иной as_of и replace=False: отказ с DemoDataError.
      - При иной as_of и replace=True: пересборка (реализуется в задаче 2.1).
    """
    keys = get_existing_demo_keys(session)
    has_records = any(bool(v) for v in keys.values())

    if not has_records:
        stats = load_demo_data(session, as_of)
        return "created", stats

    existing_as_of = detect_demo_as_of(session)
    if existing_as_of is None:
        raise DemoDataError(
            "Демонабор не полон или поврежден: "
            f"отсутствует опорное движение {DEMO_BASE_RECEIPT_DOC}"
        )

    verify_demo_keys(session, keys)

    if as_of == existing_as_of:
        stats = {
            "locations": len(keys["locations"]),
            "suppliers": len(keys["suppliers"]),
            "items": len(keys["items"]),
            "supplier_conditions": len(DEMO_CONDITIONS),
            "movements": len(keys["movements"]),
            "batches": len(keys["batches"]),
            "orders": len(keys["orders"]),
        }
        return "idempotent", stats

    if not replace:
        raise DemoDataError(
            f"Демонабор уже создан на дату {existing_as_of.isoformat()}. "
            f"Для пересборки на дату {as_of.isoformat()} укажите флаг --replace."
        )

    raise NotImplementedError("Режим --replace будет реализован в задаче 2.1")
