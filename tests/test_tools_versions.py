"""Тесты проверки закреплённых версий тестовых инструментов в окружении."""

from importlib.metadata import version

import httpx
import pytest


def test_tool_versions() -> None:
    """Проверка соответствия версий pytest, ruff и httpx согласованной матрице."""
    assert pytest.__version__ == "9.1.1"
    assert httpx.__version__ == "0.28.1"
    assert version("ruff") == "0.16.9"
