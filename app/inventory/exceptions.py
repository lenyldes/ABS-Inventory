"""Доменные исключения складского модуля."""

from datetime import date
from decimal import Decimal
from typing import Any


class InventoryError(Exception):
    """Базовое исключение домена склада."""

    def __init__(
        self,
        message: str,
        code: str = "INVENTORY_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class InsufficientStockError(InventoryError):
    """Недостаточно доступного остатка для выполнения операции."""

    def __init__(
        self,
        requested: Decimal,
        available: Decimal,
        sku: str | None = None,
        location: str | None = None,
    ) -> None:
        message = f"Недостаточно доступного остатка: запрошено {requested}, доступно {available}"
        details = {
            "requested": str(requested),
            "available": str(available),
        }
        if sku:
            details["sku"] = sku
        if location:
            details["location"] = location
        super().__init__(
            message=message,
            code="INSUFFICIENT_STOCK",
            details=details,
        )


class HistoricalSufficiencyError(InventoryError):
    """Операция приводит к дефициту остатка в последующие даты."""

    def __init__(
        self,
        deficit_date: date,
        deficit_qty: Decimal,
        conflicting_doc_number: str | None = None,
        batch_id: int | None = None,
    ) -> None:
        message = (
            f"Нарушение исторической обеспеченности на дату {deficit_date.isoformat()}: "
            f"дефицит {deficit_qty}"
        )
        details: dict[str, Any] = {
            "deficit_date": deficit_date.isoformat(),
            "deficit_qty": str(deficit_qty),
        }
        if conflicting_doc_number:
            details["conflicting_doc_number"] = conflicting_doc_number
        if batch_id is not None:
            details["batch_id"] = batch_id
        super().__init__(
            message=message,
            code="HISTORICAL_DEFICIT",
            details=details,
        )


class ExcessReturnError(InventoryError):
    """Количество возврата превышает остаток по исходной строке расхода."""

    def __init__(
        self,
        requested_return: Decimal,
        max_allowed_return: Decimal,
        parent_allocation_id: int,
    ) -> None:
        message = (
            f"Возврат {requested_return} превышает допустимое количество {max_allowed_return} "
            f"по строке расхода {parent_allocation_id}"
        )
        details = {
            "requested_return": str(requested_return),
            "max_allowed_return": str(max_allowed_return),
            "parent_allocation_id": parent_allocation_id,
        }
        super().__init__(
            message=message,
            code="EXCESS_RETURN",
            details=details,
        )


class InvalidMovementError(InventoryError):
    """Недопустимые параметры движения."""

    def __init__(
        self,
        message: str,
        code: str = "INVALID_MOVEMENT",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)


class DocumentDuplicateError(InventoryError):
    """Дубликат номера документа на объекте."""

    def __init__(self, doc_number: str, location_code: str) -> None:
        message = (
            f"Документ с номером '{doc_number}' уже зарегистрирован на объекте '{location_code}'"
        )
        details = {
            "doc_number": doc_number,
            "location": location_code,
        }
        super().__init__(
            message=message,
            code="DOCUMENT_DUPLICATE",
            details=details,
        )


class EntityNotFoundError(InventoryError):
    """Связанная сущность не найдена в системе."""

    def __init__(self, entity_name: str, identifier: Any) -> None:
        message = f"Сущность {entity_name} с идентификатором '{identifier}' не найдена"
        details = {"entity": entity_name, "identifier": str(identifier)}
        super().__init__(message=message, code="NOT_FOUND", details=details)
