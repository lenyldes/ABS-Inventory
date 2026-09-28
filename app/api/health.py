"""Маршрут проверки готовности сервиса."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.database import check_database_readiness

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Схема ответа проверки готовности."""

    status: str
    database: str


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        status.HTTP_200_OK: {"description": "Сервис и база данных готовы к работе"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "База данных недоступна или схема не подготовлена"
        },
    },
)
def get_health() -> JSONResponse:
    """Проверка доступности приложения, актуальности миграций и целостности схемы."""
    is_ready, db_status = check_database_readiness()
    if is_ready:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "healthy", "database": "available"},
        )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "unhealthy", "database": db_status},
    )
