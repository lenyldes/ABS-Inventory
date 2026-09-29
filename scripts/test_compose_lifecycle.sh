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
MAX_WAIT=30
WAITED=0
until curl -s "http://localhost:${PORT}/health" | grep -q '"status":"healthy"'; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ "${WAITED}" -ge "${MAX_WAIT}" ]; then
        echo "Ошибка: тайм-аут ожидания готовности /health на порту ${PORT}" >&2
        COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose logs app >&2
        exit 1
    fi
done
echo "Сервис успешно ответил healthy 200 на чистой БД."

echo "Проверка складского API по стартовым сидам..."
curl -s "http://localhost:${PORT}/api/stock?location=MS-01" | grep -q '"sku":"OIL-001"'
curl -s "http://localhost:${PORT}/api/stock/OIL-001?location=MS-01" | grep -q '"batch_number":"SEED-BATCH-OIL-01"'
curl -s "http://localhost:${PORT}/api/movements" | grep -q '"doc_number":"SEED-REC-001"'
echo "Складской API успешно отдал корректные данные по стартовым движениям."
DEMO_STATUS=$(curl -fsS "http://localhost:${PORT}/api/demo/status")
printf '%s' "${DEMO_STATUS}" | python3 -c '
import json
import sys
from datetime import date

status = json.load(sys.stdin)
assert status["ready"] is True
date.fromisoformat(status["as_of"])
'

echo "=== [3/5] Изменение живых данных на стенде ==="

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
AS_OF=$(printf '%s' "${DEMO_STATUS}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["as_of"])')
curl -fsS -H 'Content-Type: application/json' \
    -d "{\"operation_date\":\"${AS_OF}\",\"sku\":\"DEMO-OIL\",\"location\":\"DEMO-MS-01\",\"type\":\"receipt\",\"quantity\":\"2.000\",\"doc_number\":\"DEMO-LIVE-REC-01\",\"batch_number\":\"DEMO-LIVE-BATCH-01\",\"unit_price\":\"100.00\"}" \
    "http://localhost:${PORT}/api/movements" | python3 -c '
import json,sys
body=json.load(sys.stdin)
assert body["current_stock"] == "52.000"
'

echo "=== [4/5] Остановка контейнеров без удаления тома (down) и повторный запуск (up) ==="
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose down
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
POSTGRES_PORT="${POSTGRES_PORT}" \
PORT="${PORT}" \
ABS_DB_CONTAINER="${PROJECT_NAME}_db" \
ABS_APP_CONTAINER="${PROJECT_NAME}_app" \
docker compose up -d db app

echo "Ожидание готовности после перезапуска..."
MAX_WAIT=30
WAITED=0
until curl -s "http://localhost:${PORT}/health" | grep -q '"status":"healthy"'; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ "${WAITED}" -ge "${MAX_WAIT}" ]; then
        echo "Ошибка: тайм-аут ожидания готовности /health после перезапуска" >&2
        COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose logs app >&2
        exit 1
    fi
done

echo "Проверка восстановления исходных данных на сохранённом томе..."
NEW_AS_OF=$(curl -fsS "http://localhost:${PORT}/api/demo/status" | python3 -c '
import json,sys
from datetime import datetime
from zoneinfo import ZoneInfo
body=json.load(sys.stdin)
assert body == {"ready": True, "as_of": datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()}
print(body["as_of"])
')
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose exec -T app python -c '
from sqlalchemy import func
from app.models.catalog import Item
from app.core.database import get_session_factory
f = get_session_factory()
s = f()
it = s.query(Item).filter(Item.sku == "PERSIST-VOL-01").first()
assert it is None, "Пользовательская запись сохранилась после сброса"
demo_count = s.query(func.count(Item.id)).filter(Item.sku.like("DEMO-%")).scalar()
assert demo_count == 9, f"Неверное число DEMO-SKU: {demo_count}"
s.close()
'
curl -fsS "http://localhost:${PORT}/api/stock?sku=DEMO-OIL&location=DEMO-MS-01&as_of=${NEW_AS_OF}" | python3 -c '
import json,sys
body=json.load(sys.stdin)
assert body["items"][0]["current_stock"] == "50.000"
'
echo "Исходные данные восстановлены, правки посетителя удалены."

echo "=== [5/5] Очистка тестового проекта и тома (down -v) ==="
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose down -v --remove-orphans
echo "Сквозной тест Compose на отдельном томе успешно пройден!"
