"""Проверка разрядности числовых полей ответа прогноза."""

import pytest
from pydantic import ValidationError

from app.api.forecast_schemas import ForecastResponse


@pytest.mark.parametrize(
    ("field_name", "maximum", "overflow"),
    [
        ("average_daily_consumption", "999999.999999", "1000000.000000"),
        *[
            (name, "999999999.999", "1000000000.000")
            for name in (
                "forecast_consumption",
                "safety_stock",
                "current_stock",
                "available_stock",
                "incoming_qty",
                "reorder_point",
                "recommended_qty",
            )
        ],
        ("unit_price", "9999999999.99", "10000000000.00"),
        ("total_cost", "9999999999.99", "10000000000.00"),
    ],
)
def test_forecast_response_decimal_precision_limit(
    field_name: str, maximum: str, overflow: str
) -> None:
    """Каждое числовое поле принимает 12 разрядов и отвергает 13-й."""
    payload = {
        "sku": "SKU",
        "location": "LOC",
        "as_of": "2026-09-01",
        "horizon_start": "2026-09-02",
        "horizon_end": "2026-09-02",
        "days_count": 1,
        "average_daily_consumption": "0.000000",
        "forecast_consumption": "0.000",
        "safety_stock": "0.000",
        "current_stock": "0.000",
        "available_stock": "0.000",
        "incoming_qty": "0.000",
        "reorder_point": None,
        "recommended_qty": "0.000",
        "unit_price": None,
        "total_cost": None,
        "is_history_complete": False,
        "history_days": 0,
        "daily_forecast": [],
        "explanation": {"data_used": [], "formulas": [], "assumptions": []},
        "warnings": [],
    }

    payload[field_name] = maximum
    response = ForecastResponse.model_validate(payload)
    assert response.model_dump(mode="json")[field_name] == maximum

    payload[field_name] = overflow
    with pytest.raises(ValidationError) as exc_info:
        ForecastResponse.model_validate(payload)
    assert any(error["loc"] == (field_name,) for error in exc_info.value.errors())
