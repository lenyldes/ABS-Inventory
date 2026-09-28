"""Основной модуль приложения FastAPI."""

from fastapi import FastAPI

from app.api.alerts import router as alerts_router
from app.api.amendments import router as amendments_router
from app.api.errors import register_error_handlers
from app.api.forecast import router as forecast_router
from app.api.health import router as health_router
from app.api.movement_history import router as movement_history_router
from app.api.movements import router as movements_router
from app.api.stock import router as stock_router

app = FastAPI(
    title="ABS Inventory & Procurement Assistant",
    version="0.1.0",
    description="Сервис складского учёта, прогнозирования потребности и закупок.",
)

register_error_handlers(app)

app.include_router(health_router)
app.include_router(movements_router)
app.include_router(movement_history_router)
app.include_router(stock_router)
app.include_router(amendments_router)
app.include_router(forecast_router)
app.include_router(alerts_router)


@app.get("/")
def read_root() -> dict[str, str]:
    """Корневой эндпоинт приложения."""
    return {"service": "ABS Inventory & Procurement Assistant", "status": "running"}
