"""Модели данных и константы для каталога контрольных сценариев demo-data."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

TEST_DEMO_AS_OF = date(2026, 9, 29)


@dataclass(frozen=True)
class DemoScenario:
    """Контрольный демонстрационный сценарий сквозной проверки API."""

    id: str
    name: str
    goal: str
    method: str
    path: str
    params: dict[str, Any] | None = None
    json_body: dict[str, Any] | None = None
    selector: dict[str, Any] | None = None
    expected: dict[str, Any] = field(default_factory=dict)
    forecast_expected: dict[str, Any] | None = None
    stock_expected: dict[str, Any] | None = None
