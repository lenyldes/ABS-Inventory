"""Основной модуль приложения FastAPI."""

from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(
    title="ABS Inventory & Procurement Assistant",
    version="0.1.0",
    description="Сервис складского учёта, прогнозирования потребности и закупок.",
)

app.include_router(health_router)


@app.get("/")
def read_root() -> dict[str, str]:
    """Корневой эндпоинт приложения."""
    return {"service": "ABS Inventory & Procurement Assistant", "status": "running"}
