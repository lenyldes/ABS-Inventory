"""Инспекция и сверка деловых ключей демонстрационных данных."""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.demo_data.catalog import (
    DEMO_CONDITIONS,
    DEMO_ITEM_SKUS,
    DEMO_LOCATION_CODES,
    DEMO_SUPPLIER_IDS,
)
from app.demo_data.movements import (
    DEMO_BASE_RECEIPT_DOC,
    DEMO_BASE_RECEIPT_OFFSET,
    DEMO_BATCH_NUMBERS,
    DEMO_MOVEMENT_DOC_NUMBERS,
    build_demo_movement_definitions,
)
from app.demo_data.orders import DEMO_ORDER_DOC_NUMBERS
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder, SupplierCondition


class DemoDataError(Exception):
    """Базовое исключение для ошибок демонстрационных данных."""


def detect_demo_as_of(session: Session) -> date | None:
    """Определяет контрольную дату as_of существующего набора по опорному приходу масла.

    Опорное движение DEMO-REC-OIL-BASE имеет фиксированное смещение
    DEMO_BASE_RECEIPT_OFFSET (-100 дней). Если движение найдено, as_of
    вычисляется как operation_date - DEMO_BASE_RECEIPT_OFFSET (т.е. + 100 дней).
    Если движение отсутствует, возвращает None.
    """
    base_m = session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).first()
    if base_m is None:
        return None
    return base_m.operation_date - timedelta(days=DEMO_BASE_RECEIPT_OFFSET)


def get_existing_demo_keys(session: Session) -> dict[str, set[str]]:
    """Возвращает существующие в базе данных деловые ключи с префиксом DEMO-."""
    return {
        "locations": {
            c for (c,) in session.query(Location.code).filter(Location.code.like("DEMO-%")).all()
        },
        "suppliers": {
            s
            for (s,) in session.query(Supplier.supplier_id)
            .filter(Supplier.supplier_id.like("DEMO-%"))
            .all()
        },
        "items": {sku for (sku,) in session.query(Item.sku).filter(Item.sku.like("DEMO-%")).all()},
        "movements": {
            doc
            for (doc,) in session.query(Movement.doc_number)
            .filter(Movement.doc_number.like("DEMO-%"))
            .all()
        },
        "batches": {
            b
            for (b,) in session.query(Batch.batch_number)
            .filter(Batch.batch_number.like("DEMO-%"))
            .all()
        },
        "orders": {
            doc
            for (doc,) in session.query(PurchaseOrder.doc_number)
            .filter(PurchaseOrder.doc_number.like("DEMO-%"))
            .all()
        },
    }


def verify_demo_keys(
    session: Session,
    existing_keys: dict[str, set[str]],
    as_of: date | None = None,
) -> None:
    """Сверяет существующие ключи с ожидаемым полным перечнем демонабора.

    При недостающих или лишних ключах вызывает DemoDataError.
    При передаче as_of также выполняет сверку значений записей (verify_demo_values).
    """
    expected = {
        "locations": (DEMO_LOCATION_CODES, "объекты (Location)"),
        "suppliers": (DEMO_SUPPLIER_IDS, "поставщики (Supplier)"),
        "items": (DEMO_ITEM_SKUS, "номенклатура (Item)"),
        "movements": (DEMO_MOVEMENT_DOC_NUMBERS, "движения (Movement)"),
        "batches": (DEMO_BATCH_NUMBERS, "партии (Batch)"),
        "orders": (DEMO_ORDER_DOC_NUMBERS, "заказы (PurchaseOrder)"),
    }

    errors: list[str] = []
    for entity, (exp_keys, entity_name) in expected.items():
        actual_keys = existing_keys.get(entity, set())
        missing = exp_keys - actual_keys
        extra = actual_keys - exp_keys
        if missing:
            sample = sorted(missing)[:3]
            suffix = "..." if len(missing) > 3 else ""
            errors.append(f"{entity_name}: отсутствуют {sample}{suffix}")
        if extra:
            sample = sorted(extra)[:3]
            suffix = "..." if len(extra) > 3 else ""
            errors.append(f"{entity_name}: лишние {sample}{suffix}")

    demo_cond_count = (
        session.query(SupplierCondition)
        .join(Item, SupplierCondition.item_id == Item.id)
        .filter(Item.sku.in_(DEMO_ITEM_SKUS))
        .count()
    )
    if demo_cond_count != len(DEMO_CONDITIONS):
        errors.append(
            f"закупочные условия: ожидается {len(DEMO_CONDITIONS)}, обнаружено {demo_cond_count}"
        )

    if errors:
        raise DemoDataError(
            f"Конфликт или неполнота демонстрационного набора ({'; '.join(errors)})"
        )

    if as_of is not None:
        verify_demo_values(session, as_of)


def verify_demo_values(session: Session, as_of: date) -> None:
    """Сверяет значимые поля записей демонстрационного набора с эталоном.

    Проверяет количества, даты и типы складских движений, а также
    сроки годности связанных партий. При расхождениях вызывает DemoDataError.
    """
    expected_defs = build_demo_movement_definitions()
    movements = {
        m.doc_number: m
        for m in session.query(Movement).filter(Movement.doc_number.like("DEMO-%")).all()
    }
    batches = {
        b.batch_number: b
        for b in session.query(Batch).filter(Batch.batch_number.like("DEMO-%")).all()
    }

    errors: list[str] = []
    for mov_def in expected_defs:
        m = movements.get(mov_def.doc_number)
        if m is None:
            errors.append(f"движение {mov_def.doc_number}: запись отсутствует")
            continue
        if m.quantity != mov_def.quantity:
            errors.append(
                f"движение {mov_def.doc_number}: "
                f"количество {m.quantity} != эталон {mov_def.quantity}"
            )
        expected_date = mov_def.resolve_date(as_of)
        if m.operation_date != expected_date:
            errors.append(
                f"движение {mov_def.doc_number}: дата {m.operation_date} != эталон {expected_date}"
            )
        if m.type != mov_def.movement_type:
            errors.append(
                f"движение {mov_def.doc_number}: тип {m.type} != эталон {mov_def.movement_type}"
            )
        if mov_def.batch_number and mov_def.expiry_offset_days is not None:
            b = batches.get(mov_def.batch_number)
            if b is not None:
                expected_expiry = mov_def.resolve_expiry_date(as_of)
                if b.expiry_date != expected_expiry:
                    errors.append(
                        f"партия {mov_def.batch_number}: "
                        f"срок годности {b.expiry_date} != эталон {expected_expiry}"
                    )

    if errors:
        sample = errors[:3]
        suffix = f" (всего расхождений: {len(errors)})" if len(errors) > 3 else ""
        raise DemoDataError(
            f"Несоответствие значений демонстрационного набора эталону: {'; '.join(sample)}{suffix}"
        )
