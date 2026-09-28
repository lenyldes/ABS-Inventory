"""Тесты валидации переменных окружения и конфигурации."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_config_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка ошибки валидации при отсутствии обязательной переменной DATABASE_URL."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    errors = exc_info.value.errors()
    assert any(err["loc"] == ("DATABASE_URL",) for err in errors)


def test_config_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка успешной инициализации настроек с валидными переменными."""
    db_url = "postgresql+psycopg://user:secret@localhost:5432/test_db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PORT", "9000")

    settings = Settings(_env_file=None)
    assert settings.database_url == db_url
    assert settings.app_env == "test"
    assert settings.port == 9000
