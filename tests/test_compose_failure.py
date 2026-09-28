"""Интеграционные тесты сбоя подготовки во время запуска Compose на изолированном томе.

Проверяет:
1. Сбой миграции во время запуска: повреждённая ревизия в БД -> HTTP-сервер
   не стартует, ошибка миграции зафиксирована в журнале контейнера app.
2. Сбой загрузки сидов во время запуска: конфликт данных сидов -> HTTP-сервер
   не стартует, ошибка загрузки сидов зафиксирована в журнале контейнера app.
3. Полная изоляция: отдельный Compose-проект, порты и именованный том,
   гарантированная очистка только тестовых ресурсов в блоке finally.
"""

import os
import shutil
import subprocess
import time

import httpx
import pytest

TEST_MIG_PROJECT = "abs_compose_mig_fail_test"
TEST_MIG_PG_PORT = "5441"
TEST_MIG_APP_PORT = "8011"

TEST_SEED_PROJECT = "abs_compose_seed_fail_test"
TEST_SEED_PG_PORT = "5442"
TEST_SEED_APP_PORT = "8012"


def _run_compose(
    cmd: list[str],
    env: dict[str, str],
    project: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Выполняет команду docker compose для изолированного тестового проекта."""
    full_cmd = ["docker", "compose", "-p", project] + cmd
    return subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


def _wait_for_db_ready(env: dict[str, str], project: str, timeout: float = 30.0) -> None:
    """Ожидает готовности PostgreSQL внутри изолированного контейнера db."""
    start = time.time()
    while time.time() - start < timeout:
        res = _run_compose(
            ["exec", "-T", "db", "pg_isready", "-U", "abs_user", "-d", "abs_inventory"],
            env,
            project,
            check=False,
        )
        if res.returncode == 0:
            return
        time.sleep(1.0)
    raise TimeoutError(f"PostgreSQL в проекте {project} не стал готов за {timeout}с.")


def _assert_http_server_not_started(url: str, duration_sec: float = 5.0) -> None:
    """Убеждается, что HTTP-сервер не стартует и не отдаёт 200 в течение заданного времени."""
    start = time.time()
    while time.time() - start < duration_sec:
        try:
            resp = httpx.get(url, timeout=1.0)
            if resp.status_code == 200:
                pytest.fail(
                    f"HTTP-сервер неожиданно запустился и ответил 200 на {url} "
                    f"несмотря на сбой подготовки!"
                )
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(1.0)


@pytest.mark.skipif(
    not shutil.which("docker"),
    reason="Тест требует доступности Docker CLI на хосте для управления Compose томами",
)
def test_compose_startup_failure_on_migration_error() -> None:
    """Проверяет сбой миграции во время запуска: uvicorn не стартует, ошибка в логах."""
    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": TEST_MIG_PROJECT,
            "POSTGRES_PORT": TEST_MIG_PG_PORT,
            "PORT": TEST_MIG_APP_PORT,
            "ABS_DB_CONTAINER": f"{TEST_MIG_PROJECT}_db",
            "ABS_APP_CONTAINER": f"{TEST_MIG_PROJECT}_app",
            "ABS_TEST_CONTAINER": f"{TEST_MIG_PROJECT}_test",
        }
    )
    health_url = f"http://localhost:{TEST_MIG_APP_PORT}/health"

    # Гарантируем чистый старт изолированного тестового проекта
    _run_compose(["down", "-v", "--remove-orphans"], env, TEST_MIG_PROJECT, check=False)

    try:
        # 1. Запускаем только PostgreSQL на изолированном томе
        _run_compose(["up", "-d", "db"], env, TEST_MIG_PROJECT)
        _wait_for_db_ready(env, TEST_MIG_PROJECT)

        # 2. Повреждаем состояние миграции в БД: записываем фиктивную ревизию
        corrupt_sql = (
            "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL PRIMARY KEY); "
            "INSERT INTO alembic_version VALUES ('corrupted_startup_rev');"
        )
        _run_compose(
            [
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "abs_user",
                "-d",
                "abs_inventory",
                "-c",
                corrupt_sql,
            ],
            env,
            TEST_MIG_PROJECT,
        )

        # 3. Запускаем сервис app (он выполняет: alembic upgrade head && seeds && uvicorn)
        _run_compose(["up", "-d", "app"], env, TEST_MIG_PROJECT)

        # 4. Проверяем, что HTTP-сервер не стартует
        _assert_http_server_not_started(health_url, duration_sec=5.0)

        # 5. Проверяем, что причина сбоя зафиксирована в журнале контейнера app
        logs_res = _run_compose(["logs", "app"], env, TEST_MIG_PROJECT, check=False)
        app_logs = logs_res.stdout + logs_res.stderr
        assert (
            "corrupted_startup_rev" in app_logs
            or "Can't locate revision identified by" in app_logs
            or "alembic" in app_logs.lower()
        ), f"В журнале app отсутствует причина сбоя миграции:\n{app_logs}"

    finally:
        # Гарантированная очистка только изолированных ресурсов данного теста
        _run_compose(["down", "-v", "--remove-orphans"], env, TEST_MIG_PROJECT, check=False)


@pytest.mark.skipif(
    not shutil.which("docker"),
    reason="Тест требует доступности Docker CLI на хосте для управления Compose томами",
)
def test_compose_startup_failure_on_seed_error() -> None:
    """Проверяет сбой загрузки сидов во время запуска: uvicorn не стартует, ошибка в логах."""
    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": TEST_SEED_PROJECT,
            "POSTGRES_PORT": TEST_SEED_PG_PORT,
            "PORT": TEST_SEED_APP_PORT,
            "ABS_DB_CONTAINER": f"{TEST_SEED_PROJECT}_db",
            "ABS_APP_CONTAINER": f"{TEST_SEED_PROJECT}_app",
            "ABS_TEST_CONTAINER": f"{TEST_SEED_PROJECT}_test",
        }
    )
    health_url = f"http://localhost:{TEST_SEED_APP_PORT}/health"

    # Гарантируем чистый старт изолированного тестового проекта
    _run_compose(["down", "-v", "--remove-orphans"], env, TEST_SEED_PROJECT, check=False)

    try:
        # 1. Запускаем только PostgreSQL на изолированном томе
        _run_compose(["up", "-d", "db"], env, TEST_SEED_PROJECT)
        _wait_for_db_ready(env, TEST_SEED_PROJECT)

        # 2. Применяем миграции корректно
        _run_compose(
            ["run", "--rm", "app", "alembic", "upgrade", "head"],
            env,
            TEST_SEED_PROJECT,
        )

        # 3. Добавляем заведомо непроходимое ограничение схемы, приводящее к сбою загрузки сидов
        corrupt_seed_sql = "ALTER TABLE items ADD CONSTRAINT fail_seed_startup_check CHECK (false);"
        _run_compose(
            [
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "abs_user",
                "-d",
                "abs_inventory",
                "-c",
                corrupt_seed_sql,
            ],
            env,
            TEST_SEED_PROJECT,
        )

        # 4. Запускаем сервис app (alembic head успешен, но seeds падают -> uvicorn не стартует)
        _run_compose(["up", "-d", "app"], env, TEST_SEED_PROJECT)

        # 5. Проверяем, что HTTP-сервер не стартует
        _assert_http_server_not_started(health_url, duration_sec=5.0)

        # 6. Проверяем, что причина сбоя зафиксирована в журнале контейнера app
        logs_res = _run_compose(["logs", "app"], env, TEST_SEED_PROJECT, check=False)
        app_logs = logs_res.stdout + logs_res.stderr
        assert (
            "Ошибка при загрузке сидов" in app_logs
            or "fail_seed_startup_check" in app_logs
            or "CheckViolation" in app_logs
        ), f"В журнале app отсутствует причина сбоя загрузки сидов:\n{app_logs}"

    finally:
        # Гарантированная очистка только изолированных ресурсов данного теста
        _run_compose(["down", "-v", "--remove-orphans"], env, TEST_SEED_PROJECT, check=False)
