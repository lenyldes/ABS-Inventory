"""Идемпотентный загрузчик начальных данных (сидов) в базу данных."""

import logging
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.inventory.operations import register_consume, register_receipt
from app.inventory.repository import is_doc_number_active
from app.models.catalog import Item, Location, Supplier
from app.models.procurement import SupplierCondition
from app.seeds.data import (
    SEED_CONDITIONS,
    SEED_ITEMS,
    SEED_LOCATIONS,
    SEED_MOVEMENTS,
    SEED_SUPPLIERS,
)

logger = logging.getLogger(__name__)


def load_seeds(session: Session) -> dict[str, int]:
    """Загружает начальные данные в БД с гарантией идемпотентности.

    Вставляет отсутствующие записи по уникальным деловым ключам (code,
    supplier_id, sku, пара item_id + supplier_id, doc_number на объекте)
    и не перезаписывает существующие пользовательские данные.

    Returns:
        Словарь с количеством созданных записей по каждому типу.
    """
    stats = {
        "locations": 0,
        "suppliers": 0,
        "items": 0,
        "supplier_conditions": 0,
        "movements": 0,
    }

    # 1. Загрузка объектов (филиалов)
    for loc in SEED_LOCATIONS:
        existing = session.query(Location).filter(Location.code == loc["code"]).first()
        if existing is None:
            session.add(Location(code=loc["code"], name=loc["name"]))
            stats["locations"] += 1

    # 2. Загрузка поставщиков
    for sup in SEED_SUPPLIERS:
        existing = (
            session.query(Supplier).filter(Supplier.supplier_id == sup["supplier_id"]).first()
        )
        if existing is None:
            session.add(Supplier(supplier_id=sup["supplier_id"], name=sup["name"]))
            stats["suppliers"] += 1

    # 3. Загрузка товаров
    for it in SEED_ITEMS:
        existing = session.query(Item).filter(Item.sku == it["sku"]).first()
        if existing is None:
            session.add(
                Item(
                    sku=it["sku"],
                    name=it["name"],
                    category=it["category"],
                    unit=it["unit"],
                )
            )
            stats["items"] += 1

    # Фиксируем добавленные справочники, чтобы получить их id
    session.flush()

    # 4. Загрузка закупочных условий
    for cond in SEED_CONDITIONS:
        item = session.query(Item).filter(Item.sku == cond["item_sku"]).first()
        supplier = (
            session.query(Supplier).filter(Supplier.supplier_id == cond["supplier_id"]).first()
        )
        if not item or not supplier:
            continue

        existing_cond = (
            session.query(SupplierCondition)
            .filter(
                SupplierCondition.item_id == item.id,
                SupplierCondition.supplier_id == supplier.id,
            )
            .first()
        )
        if existing_cond is None:
            is_primary = cond["is_primary"]
            if is_primary:
                has_primary = (
                    session.query(SupplierCondition)
                    .filter(
                        SupplierCondition.item_id == item.id,
                        SupplierCondition.is_primary.is_(True),
                    )
                    .first()
                ) is not None
                if has_primary:
                    is_primary = False

            session.add(
                SupplierCondition(
                    item_id=item.id,
                    supplier_id=supplier.id,
                    lead_time_days=cond["lead_time_days"],
                    package_size=cond["package_size"],
                    min_order_qty=cond["min_order_qty"],
                    estimated_price=cond["estimated_price"],
                    is_primary=is_primary,
                )
            )
            stats["supplier_conditions"] += 1

    session.flush()

    # 5. Загрузка минимальных складских движений и партий
    tz = ZoneInfo("Europe/Moscow")
    base_date = datetime.now(tz).date()

    for m in SEED_MOVEMENTS:
        loc = session.query(Location).filter(Location.code == m["location"]).first()
        if not loc:
            continue
        item = session.query(Item).filter(Item.sku == m["sku"]).first()
        if not item:
            continue

        if is_doc_number_active(session, loc.id, m["doc_number"]):
            continue

        op_date = base_date - timedelta(days=m["days_ago"])
        m_type = m["type"]
        if m_type == "receipt":
            exp_date = (
                base_date + timedelta(days=m["expiry_days_ahead"])
                if m.get("expiry_days_ahead")
                else None
            )
            register_receipt(
                session,
                item=item,
                location=loc,
                operation_date=op_date,
                quantity=m["quantity"],
                doc_number=m["doc_number"],
                batch_number=m["batch_number"],
                expiry_date=exp_date,
                unit_price=m["unit_price"],
                supplier_id=m.get("supplier_id"),
            )
            stats["movements"] += 1
        elif m_type == "consume":
            register_consume(
                session,
                item=item,
                location=loc,
                operation_date=op_date,
                quantity=m["quantity"],
                doc_number=m["doc_number"],
            )
            stats["movements"] += 1

    session.commit()
    return stats


def main() -> int:
    """Точка входа CLI для загрузки начальных данных."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    factory = get_session_factory()
    session = factory()
    try:
        stats = load_seeds(session)
        logger.info(
            "Сиды успешно загружены: создано объектов: %d, "
            "поставщиков: %d, товаров: %d, закупочных условий: %d, движений: %d",
            stats["locations"],
            stats["suppliers"],
            stats["items"],
            stats["supplier_conditions"],
            stats["movements"],
        )
        return 0

    except Exception as exc:
        session.rollback()
        logger.error("Ошибка при загрузке сидов: %s", exc)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
