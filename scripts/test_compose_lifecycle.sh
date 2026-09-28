#!/usr/bin/env bash
set -euo pipefail

# Скрипт сквозной интеграционной проверки Compose на отдельном тестовом томе
PROJECT_NAME="abs_lifecycle_volume_test"
POSTGRES_PORT="5439"
PORT="8009"

echo "=== [1/5] Очистка предыдущего тестового стенда и тома ==="
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose down -v --remove-orphans 2>/dev/null || true

echo "=== [2/5] Первый запуск стека на чистом томе ==="
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
POSTGRES_PORT="${POSTGRES_PORT}" \
PORT="${PORT}" \
ABS_DB_CONTAINER="${PROJECT_NAME}_db" \
ABS_APP_CONTAINER="${PROJECT_NAME}_app" \
docker compose up -d db app

echo "Ожидание готовности /health на порту ${PORT}..."
until curl -s "http://localhost:${PORT}/health" | grep -q '"status":"healthy"'; do
    sleep 1
done
echo "Сервис успешно ответил healthy 200 на чистой БД."

echo "=== [3/5] Добавление проверочной пользовательской записи ==="
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose exec -T app python -c '
from app.models.catalog import Item
from app.core.database import get_session_factory
f = get_session_factory()
s = f()
s.add(Item(sku="PERSIST-VOL-01", name="Тест сохранности тома", category="Тест", unit="шт"))
s.commit()
s.close()
'
echo "Запись добавлена в базу данных."

echo "=== [4/5] Остановка контейнеров без удаления тома (down) и повторный запуск (up) ==="
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose down
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
POSTGRES_PORT="${POSTGRES_PORT}" \
PORT="${PORT}" \
ABS_DB_CONTAINER="${PROJECT_NAME}_db" \
ABS_APP_CONTAINER="${PROJECT_NAME}_app" \
docker compose up -d db app

echo "Ожидание готовности после перезапуска..."
until curl -s "http://localhost:${PORT}/health" | grep -q '"status":"healthy"'; do
    sleep 1
done

echo "Проверка сохранности пользовательской записи и сидов..."
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose exec -T app python -c '
from sqlalchemy import func
from app.models.catalog import Item
from app.seeds.data import SEED_ITEMS
from app.core.database import get_session_factory
f = get_session_factory()
s = f()
it = s.query(Item).filter(Item.sku == "PERSIST-VOL-01").first()
assert it is not None, "Пользовательская запись утеряна!"
total = s.query(func.count(Item.id)).scalar()
assert total == len(SEED_ITEMS) + 1, f"Неверное число товаров: {total}"
s.close()
'
echo "Пользовательские данные успешно сохранены, сиды не продублированы."

echo "=== [5/5] Очистка тестового проекта и тома (down -v) ==="
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose down -v --remove-orphans
echo "Сквозной тест Compose на отдельном томе успешно пройден!"
