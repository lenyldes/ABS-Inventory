"""Сверка значимых полей и параметров демонстрационного набора данных."""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.demo_data.catalog import DEMO_CONDITIONS, DEMO_ITEM_SKUS
from app.demo_data.movements import build_demo_movement_definitions
from app.demo_data.orders import DEMO_ORDERS
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder, SupplierCondition

if TYPE_CHECKING:
    from app.demo_data.inspection import DemoDataError
else:
    from app.demo_data.inspection import DemoDataError


def verify_demo_values(session: Session, as_of: date) -> None:
    """Сверяет значимые поля записей демонстрационного набора с эталоном.

    Проверяет количества, даты и типы складских движений, сроки годности партий,
    параметры ожидаемых заказов и закупочных условий.
    При расхождениях вызывает DemoDataError.
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

    orders = {
        doc: (po, sku, loc_code, sup_id)
        for po, doc, sku, loc_code, sup_id in (
            session.query(
                PurchaseOrder,
                PurchaseOrder.doc_number,
                Item.sku,
                Location.code,
                Supplier.supplier_id,
            )
            .join(Item, PurchaseOrder.item_id == Item.id)
            .join(Location, PurchaseOrder.location_id == Location.id)
            .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
            .filter(PurchaseOrder.doc_number.like("DEMO-%"))
            .all()
        )
    }
    for order_def in DEMO_ORDERS:
        order_info = orders.get(order_def.doc_number)
        if order_info is None:
            errors.append(f"заказ {order_def.doc_number}: запись отсутствует")
            continue
        po, actual_sku, actual_loc, actual_sup = order_info
        if actual_sku != order_def.sku:
            errors.append(
                f"заказ {order_def.doc_number}: товар {actual_sku} != эталон {order_def.sku}"
            )
        if actual_loc != order_def.location_code:
            errors.append(
                f"заказ {order_def.doc_number}: "
                f"объект {actual_loc} != эталон {order_def.location_code}"
            )
        if actual_sup != order_def.supplier_id:
            errors.append(
                f"заказ {order_def.doc_number}: "
                f"поставщик {actual_sup} != эталон {order_def.supplier_id}"
            )
        if po.expected_qty != order_def.expected_qty:
            errors.append(
                f"заказ {order_def.doc_number}: "
                f"количество {po.expected_qty} != эталон {order_def.expected_qty}"
            )
        if po.received_qty != order_def.received_qty:
            errors.append(
                f"заказ {order_def.doc_number}: "
                f"получено {po.received_qty} != эталон {order_def.received_qty}"
            )
        if po.pending_qty != order_def.pending_qty:
            errors.append(
                f"заказ {order_def.doc_number}: "
                f"остаток {po.pending_qty} != эталон {order_def.pending_qty}"
            )
        if po.unit_price != order_def.unit_price:
            errors.append(
                f"заказ {order_def.doc_number}: "
                f"цена {po.unit_price} != эталон {order_def.unit_price}"
            )
        if po.status != order_def.status:
            errors.append(
                f"заказ {order_def.doc_number}: status {po.status} != эталон {order_def.status}"
            )
        expected_po_date = order_def.resolve_expected_date(as_of)
        if po.expected_date != expected_po_date:
            errors.append(
                f"заказ {order_def.doc_number}: "
                f"дата {po.expected_date} != эталон {expected_po_date}"
            )

    conditions = (
        session.query(SupplierCondition, Item.sku, Supplier.supplier_id)
        .join(Item, SupplierCondition.item_id == Item.id)
        .join(Supplier, SupplierCondition.supplier_id == Supplier.id)
        .filter(Item.sku.in_(DEMO_ITEM_SKUS))
        .all()
    )
    cond_map = {(sku, sup_id): sc for sc, sku, sup_id in conditions}
    for exp_cond in DEMO_CONDITIONS:
        pair = (exp_cond["item_sku"], exp_cond["supplier_id"])
        sc = cond_map.get(pair)
        if sc is None:
            errors.append(f"условие {pair}: запись отсутствует")
            continue
        if sc.lead_time_days != exp_cond["lead_time_days"]:
            errors.append(
                f"условие {pair}: "
                f"lead_time {sc.lead_time_days} != эталон {exp_cond['lead_time_days']}"
            )
        if sc.package_size != exp_cond["package_size"]:
            errors.append(
                f"условие {pair}: "
                f"package_size {sc.package_size} != эталон {exp_cond['package_size']}"
            )
        if sc.min_order_qty != exp_cond["min_order_qty"]:
            errors.append(
                f"условие {pair}: "
                f"min_order_qty {sc.min_order_qty} != эталон {exp_cond['min_order_qty']}"
            )
        if sc.estimated_price != exp_cond.get("estimated_price"):
            errors.append(
                f"условие {pair}: "
                f"price {sc.estimated_price} != эталон {exp_cond.get('estimated_price')}"
            )
        if sc.is_primary != exp_cond.get("is_primary", True):
            errors.append(
                f"условие {pair}: "
                f"is_primary {sc.is_primary} != эталон {exp_cond.get('is_primary', True)}"
            )

    if errors:
        sample = errors[:3]
        suffix = f" (всего расхождений: {len(errors)})" if len(errors) > 3 else ""
        raise DemoDataError(
            f"Несоответствие значений демонстрационного набора эталону: {'; '.join(sample)}{suffix}"
        )
