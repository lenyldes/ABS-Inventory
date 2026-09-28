"""Тесты эндпоинта проверки готовности GET /health."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Фикстура тестового HTTP-клиента FastAPI."""
    return TestClient(app)


def test_health_healthy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка возврата кода 200 и статуса healthy при доступной БД."""
    monkeypatch.setattr("app.api.health.check_database_connection", lambda: True)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "healthy", "database": "available"}


def test_health_unhealthy_and_no_secrets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Проверка возврата кода 503 при сбое соединения с БД и отсутствия секретов."""
    monkeypatch.setattr("app.api.health.check_database_connection", lambda: False)

    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data == {"status": "unhealthy", "database": "unavailable"}

    raw_text = response.text.lower()
    for sensitive in ("password", "secret", "postgresql", "psycopg", "5432"):
        assert sensitive not in raw_text
