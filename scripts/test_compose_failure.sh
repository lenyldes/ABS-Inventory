#!/usr/bin/env bash
set -euo pipefail

# Скрипт проверки сбоя миграции и сидов во время запуска Compose на изолированном томе
echo "=== Тестирование сбоя подготовки во время запуска Compose ==="

# -------------------------------------------------------------
# Сценарий 1: Сбой миграции во время запуска Compose
# -------------------------------------------------------------
MIG_PROJECT="abs_compose_mig_fail_test"
MIG_PG_PORT="5441"
MIG_APP_PORT="8011"

SEED_PROJECT="abs_compose_seed_fail_test"
SEED_PG_PORT="5442"
SEED_APP_PORT="8012"

test_migration_failure() {
    echo "--- [1/2] Проверка сбоя миграции при запуске Compose ---"
    COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans 2>/dev/null || true

    COMPOSE_PROJECT_NAME="${MIG_PROJECT}" \
    POSTGRES_PORT="${MIG_PG_PORT}" \
    PORT="${MIG_APP_PORT}" \
    ABS_DB_CONTAINER="${MIG_PROJECT}_db" \
    ABS_APP_CONTAINER="${MIG_PROJECT}_app" \
    docker compose up -d db

    until COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose exec -T db pg_isready -U abs_user -d abs_inventory >/dev/null 2>&1; do
        sleep 1
    done

    COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose exec -T db psql -U abs_user -d abs_inventory -c "
    CREATE TABLE alembic_version (version_num varchar(32) NOT NULL PRIMARY KEY);
    INSERT INTO alembic_version VALUES ('corrupted_startup_rev');
    " >/dev/null

    COMPOSE_PROJECT_NAME="${MIG_PROJECT}" \
    POSTGRES_PORT="${MIG_PG_PORT}" \
    PORT="${MIG_APP_PORT}" \
    ABS_DB_CONTAINER="${MIG_PROJECT}_db" \
    ABS_APP_CONTAINER="${MIG_PROJECT}_app" \
    docker compose up -d app

    sleep 4
    if curl -s "http://localhost:${MIG_APP_PORT}/health" >/dev/null 2>&1; then
        echo "ОШИБКА: Сервер неожиданно ответил на запросы при сбое миграции!" >&2
        COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1
        return 1
    fi

    MIG_LOGS=$(COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose logs app 2>&1)
    if ! echo "${MIG_LOGS}" | grep -q "corrupted_startup_rev"; then
        echo "ОШИБКА: В журнале контейнера app не найдена ошибка миграции!" >&2
        echo "${MIG_LOGS}" >&2
        COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1
        return 1
    fi

    COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1
    echo "Сценарий сбоя миграции успешно пройден!"
}

test_seed_failure() {
    echo "--- [2/2] Проверка сбоя загрузки сидов при запуске Compose ---"
    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans 2>/dev/null || true

    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" \
    POSTGRES_PORT="${SEED_PG_PORT}" \
    PORT="${SEED_APP_PORT}" \
    ABS_DB_CONTAINER="${SEED_PROJECT}_db" \
    ABS_APP_CONTAINER="${SEED_PROJECT}_app" \
    docker compose up -d db

    until COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose exec -T db pg_isready -U abs_user -d abs_inventory >/dev/null 2>&1; do
        sleep 1
    done

    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" \
    POSTGRES_PORT="${SEED_PG_PORT}" \
    PORT="${SEED_APP_PORT}" \
    ABS_DB_CONTAINER="${SEED_PROJECT}_db" \
    ABS_APP_CONTAINER="${SEED_PROJECT}_app" \
    docker compose run --rm app alembic upgrade head >/dev/null

    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose exec -T db psql -U abs_user -d abs_inventory -c "
    ALTER TABLE items ADD CONSTRAINT fail_seed_startup_check CHECK (false);
    " >/dev/null

    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" \
    POSTGRES_PORT="${SEED_PG_PORT}" \
    PORT="${SEED_APP_PORT}" \
    ABS_DB_CONTAINER="${SEED_PROJECT}_db" \
    ABS_APP_CONTAINER="${SEED_PROJECT}_app" \
    docker compose up -d app

    sleep 4
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "http://localhost:${SEED_APP_PORT}/health" 2>/dev/null || echo "000")
    if [ "${HTTP_CODE}" = "200" ]; then
        echo "ОШИБКА: Сервер неожиданно ответил 200 на запросы при сбое загрузки сидов!" >&2
        COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1
        return 1
    fi

    SEED_LOGS=$(COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose logs app 2>&1)
    if ! echo "${SEED_LOGS}" | grep -q "Ошибка при загрузке сидов"; then
        echo "ОШИБКА: В журнале контейнера app не найдена ошибка сидов!" >&2
        echo "${SEED_LOGS}" >&2
        COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1
        return 1
    fi

    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1
    echo "Сценарий сбоя сидов успешно пройден!"
}

LOG1=$(mktemp) || exit 1
LOG2=$(mktemp) || exit 1

cleanup_failure_all() {
    COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1 || true
    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f "${LOG1}" "${LOG2}"
}
trap cleanup_failure_all EXIT

test_migration_failure >"${LOG1}" 2>&1 &
PID1=$!

test_seed_failure >"${LOG2}" 2>&1 &
PID2=$!

FAIL=0
if ! wait "${PID1}"; then
    cat "${LOG1}" >&2
    FAIL=1
fi
if ! wait "${PID2}"; then
    cat "${LOG2}" >&2
    FAIL=1
fi

if (( FAIL )); then
    exit 1
fi

cat "${LOG1}"
cat "${LOG2}"
echo "=== Все проверки сбоя запуска Compose успешно пройдены! ==="
