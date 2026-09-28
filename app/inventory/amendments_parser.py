"""Преобразование и валидация входных структур запросов в доменные операции исправлений."""

from datetime import date
from decimal import Decimal

from app.api.amendment_schemas import OperationItem
from app.inventory.amendments_domain import (
    AllocationBatchChange,
    AllocationQuantityChange,
    AmendmentOperation,
)
from app.inventory.exceptions import AmendmentValidationError

_ALLOWED_UPDATE_FIELDS = {
    "quantity",
    "operation_date",
    "doc_number",
    "allocation_id",
    "batch_id",
    "location",
    "allocation_quantities",
}


def parse_operation_item(item: OperationItem) -> AmendmentOperation:
    """Преобразует входную схему операции в строго валидированную доменную операцию."""
    if item.expected_version < 1:
        raise AmendmentValidationError(
            f"Версия expected_version должна быть >= 1, получено: {item.expected_version}",
            code="INVALID_VERSION",
        )

    if item.action == "cancel":
        return AmendmentOperation(
            movement_id=item.movement_id,
            action="cancel",
            expected_version=item.expected_version,
            raw_fields=item.fields or {},
        )

    if item.action != "update":
        raise AmendmentValidationError(
            f"Недопустимое действие: '{item.action}'. Разрешены только 'update' и 'cancel'",
            code="INVALID_ACTION",
        )

    fields = item.fields
    if fields is None or not isinstance(fields, dict):
        raise AmendmentValidationError(
            "Для операции 'update' обязательно указание словаря 'fields'",
            code="MISSING_FIELDS",
        )

    if "sku" in fields:
        raise AmendmentValidationError(
            "Смена SKU складского движения запрещена",
            code="SKU_IMMUTABLE",
        )

    for key in fields:
        if key not in _ALLOWED_UPDATE_FIELDS:
            raise AmendmentValidationError(
                f"Недопустимое поле в fields: '{key}'",
                code="INVALID_FIELD",
            )

    quantity: Decimal | None = None
    if "quantity" in fields and fields["quantity"] is not None:
        try:
            quantity = Decimal(str(fields["quantity"]))
        except Exception as e:
            raise AmendmentValidationError(
                f"Некорректное значение quantity: {fields['quantity']}",
                code="INVALID_QUANTITY",
            ) from e
        if quantity <= Decimal("0.000"):
            raise AmendmentValidationError(
                f"Количество должно быть строго больше нуля, получено: {quantity}",
                code="INVALID_QUANTITY",
            )

    op_date: date | None = None
    if "operation_date" in fields and fields["operation_date"] is not None:
        raw_date = fields["operation_date"]
        if isinstance(raw_date, date):
            op_date = raw_date
        elif isinstance(raw_date, str):
            try:
                op_date = date.fromisoformat(raw_date)
            except ValueError as e:
                raise AmendmentValidationError(
                    f"Некорректный формат даты operation_date: '{raw_date}'",
                    code="INVALID_DATE",
                ) from e
        else:
            raise AmendmentValidationError(
                f"Некорректный тип operation_date: {type(raw_date)}",
                code="INVALID_DATE",
            )

    doc_number: str | None = None
    if "doc_number" in fields and fields["doc_number"] is not None:
        doc_number = str(fields["doc_number"]).strip()
        if not doc_number:
            raise AmendmentValidationError(
                "Номер документа doc_number не может быть пустым",
                code="INVALID_DOC_NUMBER",
            )

    location_code: str | None = None
    if "location" in fields and fields["location"] is not None:
        location_code = str(fields["location"]).strip()
        if not location_code:
            raise AmendmentValidationError(
                "Код объекта location не может быть пустым",
                code="INVALID_LOCATION",
            )

    has_alloc_id = "allocation_id" in fields and fields["allocation_id"] is not None
    has_batch_id = "batch_id" in fields and fields["batch_id"] is not None
    batch_change: AllocationBatchChange | None = None
    if has_alloc_id or has_batch_id:
        if not (has_alloc_id and has_batch_id):
            raise AmendmentValidationError(
                "Поля 'allocation_id' и 'batch_id' для смены партии должны быть указаны совместно",
                code="INVALID_BATCH_SWAP",
            )
        try:
            batch_change = AllocationBatchChange(
                allocation_id=int(fields["allocation_id"]),
                new_batch_id=int(fields["batch_id"]),
            )
        except Exception as e:
            raise AmendmentValidationError(
                "Некорректные идентификаторы allocation_id или batch_id",
                code="INVALID_BATCH_SWAP",
            ) from e

    alloc_quantities: list[AllocationQuantityChange] | None = None
    if "allocation_quantities" in fields and fields["allocation_quantities"] is not None:
        raw_allocs = fields["allocation_quantities"]
        if not isinstance(raw_allocs, list):
            raise AmendmentValidationError(
                "Поле allocation_quantities должно быть списком объектов",
                code="INVALID_ALLOCATION_QUANTITIES",
            )
        alloc_quantities = []
        for entry in raw_allocs:
            if hasattr(entry, "allocation_id") and hasattr(entry, "quantity"):
                a_id = entry.allocation_id
                a_qty = entry.quantity
            elif isinstance(entry, dict) and "allocation_id" in entry and "quantity" in entry:
                a_id = entry["allocation_id"]
                a_qty = entry["quantity"]
            else:
                raise AmendmentValidationError(
                    "Каждый элемент allocation_quantities должен содержать "
                    "allocation_id и quantity",
                    code="INVALID_ALLOCATION_QUANTITY_ITEM",
                )
            try:
                dec_qty = Decimal(str(a_qty))
            except Exception as e:
                raise AmendmentValidationError(
                    f"Некорректное количество в строке распределения: {a_qty}",
                    code="INVALID_QUANTITY",
                ) from e
            if dec_qty <= Decimal("0.000"):
                raise AmendmentValidationError(
                    f"Количество строки распределения должно быть строго > 0, получено: {dec_qty}",
                    code="INVALID_QUANTITY",
                )
            alloc_quantities.append(
                AllocationQuantityChange(allocation_id=int(a_id), quantity=dec_qty)
            )

    return AmendmentOperation(
        movement_id=item.movement_id,
        action="update",
        expected_version=item.expected_version,
        quantity=quantity,
        operation_date=op_date,
        doc_number=doc_number,
        location_code=location_code,
        allocation_quantities=tuple(alloc_quantities) if alloc_quantities is not None else None,
        allocation_batch_change=batch_change,
        raw_fields=fields,
    )


def parse_preview_operations(
    raw_operations: list[OperationItem] | None,
) -> tuple[AmendmentOperation, ...]:
    """Валидирует список операций предварительного просмотра."""
    if not raw_operations:
        raise AmendmentValidationError(
            "Список операций не может быть пустым",
            code="EMPTY_OPERATIONS",
        )
    return tuple(parse_operation_item(item) for item in raw_operations)
