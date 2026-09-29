"""Каталог контрольных демонстрационных сценариев и эталонных ответов API."""

from app.demo_data.scenario_models import TEST_DEMO_AS_OF, DemoScenario
from app.demo_data.scenarios_data import DEMO_SCENARIOS

DEMO_SCENARIOS_BY_ID: dict[str, DemoScenario] = {s.id: s for s in DEMO_SCENARIOS}
DEMO_SCENARIO_IDS: set[str] = set(DEMO_SCENARIOS_BY_ID.keys())


def get_demo_scenario(scenario_id: str) -> DemoScenario:
    """Возвращает сценарий по его стабильному идентификатору."""
    if scenario_id not in DEMO_SCENARIOS_BY_ID:
        raise KeyError(f"Неизвестный сценарий: {scenario_id}")
    return DEMO_SCENARIOS_BY_ID[scenario_id]


__all__ = [
    "DEMO_SCENARIO_IDS",
    "DEMO_SCENARIOS",
    "DEMO_SCENARIOS_BY_ID",
    "TEST_DEMO_AS_OF",
    "DemoScenario",
    "get_demo_scenario",
]
