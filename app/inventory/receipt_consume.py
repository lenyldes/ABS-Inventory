"""Сервисная логика операций поступления (receipt) и расхода (consume)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.timezone import today_in_moscow
from app.inventory.calculator import calculate_stock_balance
from app.inventory.common_validation import (
    MovementExecutionResult,
    load_history,
    validate_common_rules,
)
from app.inventory.domain import AllocationSnapshot, MovementSnapshot
from app.inventory.exceptions import (
    EntityNotFoundError,
    InvalidMovementError,
)
from app.inventory.fefo import allocate_fefo
from app.inventory.history import validate_history_sufficiency
from app.inventory.repository import (
    create_allocations,
    create_batch,
    create_movement,
    get_purchase_order_for_update,
    get_supplier_by_id,
)
from app.models.catalog import Item, Location

_ZERO = Decimal("0.000")


def register_receipt(
    session: Session,
    *,
    item: Item,
    location: Location,
    operation_date: date,
    quantity: Decimal,
    doc_number: str,
    batch_number: str,
    expiry_date: date | None,
    unit_price: Decimal,
    purchase_order_id: int | None = None,
    supplier_id: str | None = None,
) -> MovementExecutionResult:
    """Регистрирует поступление товара с созданием учётной партии."""
    validate_common_rules(session, item, location, operation_date, quantity, doc_number)

    if unit_price < Decimal("0.00"):
        raise InvalidMovementError(
            f"Цена за единицу не может быть отрицательной: {unit_price}",
            code="NEGATIVE_PRICE",
            details={"unit_price": str(unit_price)},
        )

    supplier_db_id: int | None = None
    if purchase_order_id is not None:
        po = get_purchase_order_for_update(session, purchase_order_id)
        if not po:
            raise EntityNotFoundError("PurchaseOrder", purchase_order_id)
        if po.item_id != item.id or po.location_id != location.id:
            raise InvalidMovementError(
                "Заказ поставщику не соответствует указанному товару или объекту",
                code="ORDER_MISMATCH",
            )
        if supplier_id is not None and po.supplier.supplier_id != supplier_id:
            raise InvalidMovementError(
                "Поставщик не соответствует заказу поставщику",
                code="SUPPLIER_MISMATCH",
            )
        if quantity > po.pending_qty:
            raise InvalidMovementError(
                f"Количество прихода {quantity} превышает "
                f"неполученный остаток заказа {po.pending_qty}",
                code="EXCESS_ORDER_QTY",
                details={
                    "quantity": str(quantity),
                    "pending_qty": str(po.pending_qty),
                },
            )
        po.received_qty += quantity
        po.pending_qty -= quantity
        po.status = "received" if po.pending_qty <= _ZERO else "partially_received"
        supplier_db_id = po.supplier_id
    elif supplier_id is not None:
        sup = get_supplier_by_id(session, supplier_id)
        if not sup:
            raise EntityNotFoundError("Supplier", supplier_id)
        supplier_db_id = sup.id

    batch = create_batch(
        session,
        item_id=item.id,
        location_id=location.id,
        batch_number=batch_number,
        receipt_date=operation_date,
        expiry_date=expiry_date,
        unit_price=unit_price,
        receipt_doc_number=doc_number,
    )

    mv = create_movement(
        session,
        operation_date=operation_date,
        item_id=item.id,
        location_id=location.id,
        type="receipt",
        quantity=quantity,
        doc_number=doc_number,
        batch_id=batch.id,
        purchase_order_id=purchase_order_id,
        supplier_id=supplier_db_id,
    )

    _, _, b_snaps, m_snaps = load_history(session, item.id, location.id)
    validate_history_sufficiency(b_snaps, m_snaps)

    balance = calculate_stock_balance(b_snaps, m_snaps, as_of=today_in_moscow())
    return MovementExecutionResult(
        movement=mv,
        current_stock=balance.current_stock,
        available_stock=balance.available_stock,
    )


def register_consume(
    session: Session,
    *,
    item: Item,
    location: Location,
    operation_date: date,
    quantity: Decimal,
    doc_number: str,
) -> MovementExecutionResult:
    """Регистрирует расход по алгоритму FEFO."""
    validate_common_rules(session, item, location, operation_date, quantity, doc_number)

    _, _, b_snaps, m_snaps = load_history(session, item.id, location.id)

    allocations_data = allocate_fefo(
        requested_qty=quantity,
        batches=b_snaps,
        movements_prior=m_snaps,
        operation_date=operation_date,
    )

    mv = create_movement(
        session,
        operation_date=operation_date,
        item_id=item.id,
        location_id=location.id,
        type="consume",
        quantity=quantity,
        doc_number=doc_number,
    )
    alloc_models = create_allocations(session, mv.id, list(allocations_data))

    new_alloc_snaps = tuple(
        AllocationSnapshot(
            id=a.id,
            movement_id=mv.id,
            batch_id=a.batch_id,
            quantity=a.quantity,
            unit_price=a.unit_price,
        )
        for a in alloc_models
    )
    new_mv_snap = MovementSnapshot(
        id=mv.id,
        operation_date=operation_date,
        created_at=mv.created_at,
        item_id=item.id,
        location_id=location.id,
        type="consume",
        quantity=quantity,
        doc_number=doc_number,
        allocations=new_alloc_snaps,
    )
    validate_history_sufficiency(b_snaps, m_snaps, new_movement=new_mv_snap)

    all_m_snaps = m_snaps + [new_mv_snap]
    balance = calculate_stock_balance(b_snaps, all_m_snaps, as_of=today_in_moscow())

    return MovementExecutionResult(
        movement=mv,
        current_stock=balance.current_stock,
        available_stock=balance.available_stock,
        allocations=tuple(alloc_models),
    )
