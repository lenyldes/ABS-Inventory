"""Сквозной интеграционный тест Compose на отдельном тестовом томе Docker.

Проверяет:
1. Первый запуск: миграция, сиды, демонабор и /health 200.
2. Сохранение пользовательских данных при down (без -v) и повторном up.
3. Сохранение демонабора и его даты после повторного запуска.
4. Очистка изолированного тома при завершении.
"""

import os
import shutil
import subprocess
import time

import httpx
import pytest

TEST_PROJECT_NAME = "abs_compose_lifecycle_test"
TEST_POSTGRES_PORT = "5439"
TEST_APP_PORT = "8009"


def _run_compose(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Вспомогательная функция выполнения команды docker compose."""
    full_cmd = ["docker", "compose", "-p", TEST_PROJECT_NAME] + cmd
    return subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )


def _wait_for_health(url: str, timeout: float = 30.0) -> httpx.Response:
    """Ожидает доступности /health с заданным таймаутом."""
    start = time.time()
    last_err: Exception | None = None
    while time.time() - start < timeout:
        try:
            resp = httpx.get(url, timeout=2.0)
            if resp.status_code == 200:
                return resp
        except Exception as e:
            last_err = e
        time.sleep(1.0)
    raise TimeoutError(f"Сервис по адресу {url} не ответил 200 за {timeout}c. Ошибка: {last_err}")


@pytest.mark.skipif(
    not shutil.which("docker"),
    reason="Тест требует доступности Docker CLI на хосте для управления Compose томами",
)
def test_compose_lifecycle_end_to_end_on_isolated_volume() -> None:
    """Сквозной тест Compose первого запуска, down, повторного up и сохранности тома."""
    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": TEST_PROJECT_NAME,
            "POSTGRES_PORT": TEST_POSTGRES_PORT,
            "PORT": TEST_APP_PORT,
            "ABS_DB_CONTAINER": f"{TEST_PROJECT_NAME}_db",
            "ABS_APP_CONTAINER": f"{TEST_PROJECT_NAME}_app",
            "ABS_TEST_CONTAINER": f"{TEST_PROJECT_NAME}_test",
        }
    )

    health_url = f"http://localhost:{TEST_APP_PORT}/health"

    # Гарантируем чистый старт: удаляем изолированный проект и том
    subprocess.run(
        ["docker", "compose", "-p", TEST_PROJECT_NAME, "down", "-v", "--remove-orphans"],
        capture_output=True,
        env=env,
    )

    try:
        # 1. Первый запуск на чистом тестовом томе
        _run_compose(["up", "-d", "db", "app"], env)

        # Ожидаем готовность: миграции и сиды завершены, HTTP отдает 200
        resp = _wait_for_health(health_url, timeout=30.0)
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"status": "healthy", "database": "available"}
        demo_status_url = f"http://localhost:{TEST_APP_PORT}/api/demo/status"
        demo_status = httpx.get(demo_status_url, timeout=5.0)
        assert demo_status.status_code == 200
        as_of = demo_status.json()["as_of"]
        assert demo_status.json() == {"ready": True, "as_of": as_of}

        # 2. Добавляем проверочную запись пользователя
        add_user_record_cmd = (
            "python -c '"
            "from app.models.catalog import Item; "
            "from app.core.database import get_session_factory; "
            "factory = get_session_factory(); "
            "s = factory(); "
            's.add(Item(sku="COMPOSE-VOL-01", name="Том сохранен", '
            'category="Тест", unit="шт")); '
            "s.commit(); "
            "s.close()'"
        )
        _run_compose(["exec", "-T", "app", "sh", "-c", add_user_record_cmd], env)

        # 3. Остановка проекта без флага -v (сохранение именованного тома)
        _run_compose(["down"], env)

        # 4. Повторный запуск на сохранённом томе
        _run_compose(["up", "-d", "db", "app"], env)

        # Сервис снова готов
        resp_restart = _wait_for_health(health_url, timeout=30.0)
        assert resp_restart.status_code == 200
        assert resp_restart.json() == {"status": "healthy", "database": "available"}
        demo_status_restart = httpx.get(demo_status_url, timeout=5.0)
        assert demo_status_restart.status_code == 200
        assert demo_status_restart.json() == {"ready": True, "as_of": as_of}

        # Проверяем, что запись на месте, а все девять SKU демонабора сохранились
        verify_data_cmd = (
            "python -c '"
            "from sqlalchemy import func; "
            "from app.models.catalog import Item; "
            "from app.core.database import get_session_factory; "
            "factory = get_session_factory(); "
            "s = factory(); "
            'saved = s.query(Item).filter(Item.sku == "COMPOSE-VOL-01").first(); '
            'assert saved is not None, "Пользовательская запись не найдена после перезапуска!"; '
            'assert saved.name == "Том сохранен"; '
            'demo_count = s.query(func.count(Item.id)).filter(Item.sku.like("DEMO-%")).scalar(); '
            'assert demo_count == 9, f"Неверное число DEMO-SKU: {demo_count}"; '
            "s.close()'"
        )
        _run_compose(["exec", "-T", "app", "sh", "-c", verify_data_cmd], env)

    finally:
        # 5. Очистка проекта и изолированного тестового тома
        _run_compose(["down", "-v", "--remove-orphans"], env)
