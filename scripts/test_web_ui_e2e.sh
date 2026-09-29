#!/usr/bin/env bash
set -euo pipefail

# Сквозная проверка сайта и прокси на отдельном Compose-проекте.
cd "$(dirname "$0")/.."
PROJECT_NAME="abs_web_ui_e2e_$$"
export COMPOSE_PROJECT_NAME="${PROJECT_NAME}"
export ABS_DB_CONTAINER="${PROJECT_NAME}_db"
export ABS_APP_CONTAINER="${PROJECT_NAME}_app"
export WEB_PORT=8089
export PORT=8019
export POSTGRES_PORT=5449
BASE_URL="http://localhost:${WEB_PORT}"

cleanup() {
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
    if [[ "${ABS_CLEANUP_IMAGES:-0}" == "1" ]]; then
        docker rmi "${ABS_WEB_IMAGE:-abs_web:latest}" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
cleanup

docker compose up -d web >/dev/null
for ((attempt = 0; attempt < 60; attempt++)); do
    if curl -fsS "${BASE_URL}/health" | grep -q '"status":"healthy"'; then
        break
    fi
    sleep 1
done
curl -fsS "${BASE_URL}/health" | grep -q '"status":"healthy"'
curl -fsS "${BASE_URL}/" | grep -q 'ABS Inventory'
curl -fsS "${BASE_URL}/" | grep -q '/js/main.js'
curl -fsS "${BASE_URL}/js/main.js" | grep -q 'initWarehouse'
curl -fsS "${BASE_URL}/js/warehouse.js" | grep -q '/api/movements'
curl -fsS "${BASE_URL}/styles.css" | grep -q 'table-wrap'
curl -fsS "${BASE_URL}/docs" | grep -q 'Swagger UI'
curl -fsS "${BASE_URL}/openapi.json" | grep -q '"openapi"'

AS_OF=$(curl -fsS "${BASE_URL}/api/demo/status" | python3 -c '
import json
import sys
from datetime import date

status = json.load(sys.stdin)
assert status["ready"] is True
date.fromisoformat(status["as_of"])
print(status["as_of"])
')
curl -fsS "${BASE_URL}/api/stock?as_of=${AS_OF}&limit=100" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
oil = next(item for item in data["items"] if item["sku"] == "DEMO-OIL" and item["location"] == "DEMO-MS-01")
assert oil["current_stock"] == "50.000"
'
curl -fsS "${BASE_URL}/api/stock/DEMO-EXPIRED?as_of=${AS_OF}" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
location = next(item for item in data["locations"] if item["location"] == "DEMO-MS-01")
assert location["current_stock"] == "10.000"
assert location["available_stock"] == "0.000"
assert location["batches"]
'
curl -fsS "${BASE_URL}/api/movements?sku=DEMO-OIL&date_to=${AS_OF}&limit=2&offset=2" | python3 -c '
import json
import sys

page = json.load(sys.stdin)
assert page["total"] > 2
assert page["offset"] == 2
assert len(page["items"]) == 2
assert all(item["sku"] == "DEMO-OIL" for item in page["items"])
'
curl -fsS "${BASE_URL}/api/alerts?as_of=${AS_OF}" | python3 -c '
import json
import sys

body = json.dumps(json.load(sys.stdin))
assert "DEMO-DEFICIT" in body
assert "type" in body
'
curl -fsS -H 'Content-Type: application/json' \
    -d "{\"as_of\":\"${AS_OF}\",\"horizon_months\":3}" \
    "${BASE_URL}/api/procurement/plan" | python3 -c '
import json
import sys

body = json.dumps(json.load(sys.stdin))
assert "DEMO-OIL" in body
assert "known_total" in body
'

# Повреждённый ключ делает демонабор неполным; bootstrap не допускает запуск API.
docker compose down >/dev/null
docker compose up -d db >/dev/null
docker compose exec -T db psql -U abs_user -d abs_inventory -c \
    "UPDATE items SET sku = 'DEMO-OIL-BROKEN' WHERE sku = 'DEMO-OIL';" >/dev/null
docker compose up -d app >/dev/null
docker compose up -d --no-deps web >/dev/null
sleep 5
http_code=$(curl -sS -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
    -d "{\"as_of\":\"${AS_OF}\",\"horizon_months\":3}" \
    "${BASE_URL}/api/procurement/plan" || true)
[[ "${http_code}" != "200" ]]
