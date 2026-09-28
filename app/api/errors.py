"""Обработчики ошибок HTTP API и доменных исключений склада."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.inventory.exceptions import (
    AmendmentBadRequestError,
    DocumentDuplicateError,
    EntityNotFoundError,
    InvalidPaginationError,
    InventoryError,
    StalePreviewError,
)


def _format_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Формирует унифицированный JSON-ответ с машинным кодом и русским сообщением."""
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "details": details or {},
        },
    )


async def inventory_error_handler(_: Request, exc: InventoryError) -> JSONResponse:
    """Обработчик доменных исключений складского учёта."""
    if isinstance(exc, EntityNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, (DocumentDuplicateError, StalePreviewError)):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(exc, (InvalidPaginationError, AmendmentBadRequestError)):
        status_code = status.HTTP_400_BAD_REQUEST
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    return _format_error_response(
        status_code=status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Обработчик ошибок валидации Pydantic и синтаксиса JSON."""
    errors = exc.errors()
    is_malformed_json = any(
        err.get("type") in ("json_invalid", "value_error.jsondecode")
        or "JSON decode" in str(err.get("msg", ""))
        for err in errors
    )

    if is_malformed_json:
        return _format_error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_JSON",
            message="Тело запроса содержит невалидный JSON",
            details={"errors": [str(e.get("msg")) for e in errors]},
        )

    return _format_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="VALIDATION_ERROR",
        message="Ошибка валидации входных данных",
        details={
            "errors": [f"{'.'.join(map(str, e.get('loc', [])))}: {e.get('msg')}" for e in errors]
        },
    )


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Обработчик стандартных HTTP-исключений."""
    code_map = {
        status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
        status.HTTP_404_NOT_FOUND: "NOT_FOUND",
        status.HTTP_409_CONFLICT: "CONFLICT",
        status.HTTP_422_UNPROCESSABLE_ENTITY: "VALIDATION_ERROR",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = str(exc.detail) if exc.detail else "Ошибка HTTP-запроса"
    return _format_error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
    )


async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    """Обработчик нарушений ограничений целостности базы данных."""
    err_str = str(exc).lower()
    if "uq_movements_location_doc_active" in err_str or "duplicate key" in err_str:
        return _format_error_response(
            status_code=status.HTTP_409_CONFLICT,
            code="DOCUMENT_DUPLICATE",
            message="Документ с таким номером уже зарегистрирован на объекте",
        )

    return _format_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="DATABASE_INTEGRITY_ERROR",
        message="Нарушение ограничений целостности данных",
    )


def register_error_handlers(app: FastAPI) -> None:
    """Регистрирует обработчики исключений в приложении FastAPI."""
    app.add_exception_handler(InventoryError, inventory_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(IntegrityError, integrity_error_handler)  # type: ignore[arg-type]
