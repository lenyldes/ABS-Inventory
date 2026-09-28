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

echo "--- [1/2] Проверка сбоя миграции при запуске Compose ---"
echo "Очистка предыдущего тестового стенда миграции..."
COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans 2>/dev/null || true

echo "Запуск базы данных PostgreSQL..."
COMPOSE_PROJECT_NAME="${MIG_PROJECT}" \
POSTGRES_PORT="${MIG_PG_PORT}" \
PORT="${MIG_APP_PORT}" \
ABS_DB_CONTAINER="${MIG_PROJECT}_db" \
ABS_APP_CONTAINER="${MIG_PROJECT}_app" \
docker compose up -d db

echo "Ожидание готовности PostgreSQL..."
until COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose exec -T db pg_isready -U abs_user -d abs_inventory >/dev/null 2>&1; do
    sleep 1
done

echo "Повреждение состояния ревизий Alembic в базе данных..."
COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose exec -T db psql -U abs_user -d abs_inventory -c "
CREATE TABLE alembic_version (version_num varchar(32) NOT NULL PRIMARY KEY);
INSERT INTO alembic_version VALUES ('corrupted_startup_rev');
" >/dev/null

echo "Запуск сервиса app (alembic upgrade head должен завершиться сбоем)..."
COMPOSE_PROJECT_NAME="${MIG_PROJECT}" \
POSTGRES_PORT="${MIG_PG_PORT}" \
PORT="${MIG_APP_PORT}" \
ABS_DB_CONTAINER="${MIG_PROJECT}_db" \
ABS_APP_CONTAINER="${MIG_PROJECT}_app" \
docker compose up -d app

echo "Проверка, что HTTP-сервер не стартует на порту ${MIG_APP_PORT}..."
sleep 4
if curl -s "http://localhost:${MIG_APP_PORT}/health" >/dev/null 2>&1; then
    echo "ОШИБКА: Сервер неожиданно ответил на запросы при сбое миграции!"
    COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans
    exit 1
fi
echo "HTTP-сервер не отвечает (ожидаемое поведение)."

echo "Проверка журнала контейнера app на наличие причины сбоя..."
MIG_LOGS=$(COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose logs app 2>&1)
if echo "${MIG_LOGS}" | grep -q "corrupted_startup_rev"; then
    echo "Причина сбоя миграции зафиксирована в журнале контейнера app."
else
    echo "ОШИБКА: В журнале контейнера app не найдена ошибка миграции!"
    echo "${MIG_LOGS}"
    COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans
    exit 1
fi

echo "Очистка изолированных ресурсов теста сбоя миграции..."
COMPOSE_PROJECT_NAME="${MIG_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1
echo "Сценарий сбоя миграции успешно пройден!"

# -------------------------------------------------------------
# Сценарий 2: Сбой загрузки сидов во время запуска Compose
# -------------------------------------------------------------
SEED_PROJECT="abs_compose_seed_fail_test"
SEED_PG_PORT="5442"
SEED_APP_PORT="8012"

echo "--- [2/2] Проверка сбоя загрузки сидов при запуске Compose ---"
echo "Очистка предыдущего тестового стенда сидов..."
COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans 2>/dev/null || true

echo "Запуск базы данных PostgreSQL..."
COMPOSE_PROJECT_NAME="${SEED_PROJECT}" \
POSTGRES_PORT="${SEED_PG_PORT}" \
PORT="${SEED_APP_PORT}" \
ABS_DB_CONTAINER="${SEED_PROJECT}_db" \
ABS_APP_CONTAINER="${SEED_PROJECT}_app" \
docker compose up -d db

echo "Ожидание готовности PostgreSQL..."
until COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose exec -T db pg_isready -U abs_user -d abs_inventory >/dev/null 2>&1; do
    sleep 1
done

echo "Применение миграций Alembic..."
COMPOSE_PROJECT_NAME="${SEED_PROJECT}" \
POSTGRES_PORT="${SEED_PG_PORT}" \
PORT="${SEED_APP_PORT}" \
ABS_DB_CONTAINER="${SEED_PROJECT}_db" \
ABS_APP_CONTAINER="${SEED_PROJECT}_app" \
docker compose run --rm app alembic upgrade head >/dev/null

echo "Внедрение ограничения схемы для провокации сбоя загрузки сидов..."
COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose exec -T db psql -U abs_user -d abs_inventory -c "
ALTER TABLE items ADD CONSTRAINT fail_seed_startup_check CHECK (false);
" >/dev/null

echo "Запуск сервиса app (python -m app.seeds должен завершиться сбоем)..."
COMPOSE_PROJECT_NAME="${SEED_PROJECT}" \
POSTGRES_PORT="${SEED_PG_PORT}" \
PORT="${SEED_APP_PORT}" \
ABS_DB_CONTAINER="${SEED_PROJECT}_db" \
ABS_APP_CONTAINER="${SEED_PROJECT}_app" \
docker compose up -d app

echo "Проверка, что HTTP-сервер не стартует на порту ${SEED_APP_PORT}..."
sleep 4
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "http://localhost:${SEED_APP_PORT}/health" 2>/dev/null || echo "000")
if [ "${HTTP_CODE}" = "200" ]; then
    echo "ОШИБКА: Сервер неожиданно ответил 200 на запросы при сбое загрузки сидов!"
    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans
    exit 1
fi
echo "HTTP-сервер не отвечает 200 (код: ${HTTP_CODE}, ожидаемое поведение)."

echo "Проверка журнала контейнера app на наличие ошибки загрузки сидов..."
SEED_LOGS=$(COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose logs app 2>&1)
if echo "${SEED_LOGS}" | grep -q "Ошибка при загрузке сидов"; then
    echo "Причина сбоя загрузки сидов зафиксирована в журнале контейнера app."
else
    echo "ОШИБКА: В журнале контейнера app не найдена ошибка сидов!"
    echo "${SEED_LOGS}"
    COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans
    exit 1
fi

echo "Очистка изолированных ресурсов теста сбоя сидов..."
COMPOSE_PROJECT_NAME="${SEED_PROJECT}" docker compose down -v --remove-orphans >/dev/null 2>&1
echo "Сценарий сбоя сидов успешно пройден!"

echo "=== Все проверки сбоя запуска Compose успешно пройдены! ==="
