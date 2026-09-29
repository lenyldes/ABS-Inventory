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
curl -fsS "${BASE_URL}/" | grep -q 'Проверить тестовое задание'
curl -fsS "${BASE_URL}/" | grep -q 'id="verification-screen"'
curl -fsS "${BASE_URL}/" | grep -q 'id="route-screen" class="screen" hidden'
curl -fsS "${BASE_URL}/" | grep -q 'class="screen-switch"'
curl -fsS "${BASE_URL}/" | grep -q 'class="screen-choice"'
curl -fsS "${BASE_URL}/" | grep -q 'id="warehouse"'
curl -fsS "${BASE_URL}/" | grep -q 'id="ai"'
curl -fsS "${BASE_URL}/js/main.js" | grep -q 'initWarehouse'
curl -fsS "${BASE_URL}/js/main.js" | grep -q 'initVerification'
curl -fsS "${BASE_URL}/js/verification.js" | grep -q 'exchangeJson'
curl -fsS "${BASE_URL}/js/verification.js" | grep -q 'requestEditor'
curl -fsS "${BASE_URL}/js/verification.js" | grep -q 'node("details", null, "verification-card")'
curl -fsS "${BASE_URL}/js/verification.js" | grep -q 'node("summary")'
curl -fsS "${BASE_URL}/js/verification-request.js" | grep -q 'verification-fields'
curl -fsS "${BASE_URL}/js/verification-request.js" | grep -q 'movementTypes'
curl -fsS "${BASE_URL}/js/verification-request.js" | grep -q 'alertTypes'
curl -fsS "${BASE_URL}/js/screens.js" | grep -q 'hashchange'
curl -fsS "${BASE_URL}/js/verification-read.js" | grep -q '/api/stock'
curl -fsS "${BASE_URL}/js/verification-write.js" | grep -q 'CHECK-R-'
curl -fsS "${BASE_URL}/js/main.js" | grep -q 'initAnalytics'
curl -fsS "${BASE_URL}/js/analytics.js" | grep -q '/api/procurement/plan'
curl -fsS "${BASE_URL}/js/warehouse.js" | grep -q '/api/movements'
curl -fsS "${BASE_URL}/js/movement-form.js" | grep -q '/api/movements'
! curl -fsS "${BASE_URL}/js/movement-form.js" | grep -q 'Операции с DEMO- запрещены'
curl -fsS "${BASE_URL}/styles.css" | grep -q 'table-wrap'
curl -fsS "${BASE_URL}/styles.css" | grep -q 'verification-chain { display: grid; grid-template-columns: 1fr'
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
curl -fsS "${BASE_URL}/api/stock?sku=DEMO-OIL&location=DEMO-MS-01&as_of=${AS_OF}&limit=50&offset=0" | python3 -c '
import json,sys
body=json.load(sys.stdin)
assert body["total"] == 1 and body["limit"] == 50 and body["offset"] == 0
row=body["items"][0]
assert row["current_stock"] == row["available_stock"] == "50.000"
assert row["average_daily_consumption"] == "1.000000"
'
curl -fsS "${BASE_URL}/api/movements?sku=DEMO-OIL&location=DEMO-MS-01&date_to=${AS_OF}&limit=2&offset=2" | python3 -c '
import json,sys
body=json.load(sys.stdin)
assert body["total"] > 2 and body["limit"] == 2 and body["offset"] == 2
assert len(body["items"]) == 2
'
curl -fsS -H 'Content-Type: application/json' -d "{\"sku\":\"DEMO-OIL\",\"location\":\"DEMO-MS-01\",\"as_of\":\"${AS_OF}\",\"horizon_months\":3}" \
    "${BASE_URL}/api/forecast" | python3 -c '
import json,sys
body=json.load(sys.stdin)
assert body["recommended_qty"] == "45.000" and body["total_cost"] == "4500.00"
assert body["explanation"]["formulas"]
'
curl -fsS "${BASE_URL}/api/alerts?sku=DEMO-DEFICIT&location=DEMO-MS-02&type=stockout&as_of=${AS_OF}&limit=50&offset=0" | python3 -c '
import json,sys
body=json.load(sys.stdin)
assert any(item["type"] == "stockout" and item["level"] == "critical" for item in body["items"])
'
curl -fsS "${BASE_URL}/api/alerts?sku=DEMO-IDLE&location=DEMO-MS-01&type=no_movement&as_of=${AS_OF}&limit=50&offset=0" | python3 -c '
import json,sys
body=json.load(sys.stdin)
assert any(item["type"] == "no_movement" and item["level"] == "info" for item in body["items"])
'
missing=$(curl -sS -w '\n%{http_code}' "${BASE_URL}/api/stock/CHECK-UNKNOWN-SKU")
[[ "${missing##*$'\n'}" == "404" ]]
python3 - "${missing%$'\n'*}" <<'PY'
import json,sys
body=json.loads(sys.argv[1])
assert body["message"] and body["code"]
PY
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

body = json.load(sys.stdin)
assert body["horizon_months"] == 3
assert body["horizon_start"] and body["horizon_end"]
oil = next(item for item in body["items"] if item["sku"] == "DEMO-OIL" and item["location"] == "DEMO-MS-01")
assert oil["quantity"] == "30.000"
assert oil["total_cost"] == "3000.00"
assert body["budget"]["known_total"]
assert body["budget"]["by_month"]
assert any(item["total_cost"] is None for item in body["items"])
assert any(item["order_date"] is None for item in body["items"])
assert body["explanation"]["formulas"]
'
curl -fsS -H 'Content-Type: application/json' \
    -d "{\"as_of\":\"${AS_OF}\",\"horizon_months\":1}" \
    "${BASE_URL}/api/procurement/plan" | python3 -c '
import json
import sys

body = json.load(sys.stdin)
assert body["horizon_months"] == 1
assert 28 <= body["days_count"] <= 31
'

OP_DATE=$(TZ=Europe/Moscow date +%F)
FUTURE_DATE=$(python3 - "${OP_DATE}" <<'PY'
from datetime import date, timedelta
import sys
print(date.fromisoformat(sys.argv[1]) + timedelta(days=1))
PY
)
DOC_PREFIX="WEB-E2E-${PROJECT_NAME}"
receipt=$(curl -fsS -H 'Content-Type: application/json' \
    -d "{\"operation_date\":\"${OP_DATE}\",\"sku\":\"OIL-001\",\"location\":\"MS-01\",\"type\":\"receipt\",\"quantity\":\"2.000\",\"doc_number\":\"${DOC_PREFIX}-REC\",\"batch_number\":\"${DOC_PREFIX}-BATCH\",\"unit_price\":\"100.00\"}" \
    "${BASE_URL}/api/movements")
consume=$(curl -fsS -H 'Content-Type: application/json' \
    -d "{\"operation_date\":\"${OP_DATE}\",\"sku\":\"OIL-001\",\"location\":\"MS-01\",\"type\":\"consume\",\"quantity\":\"1.000\",\"doc_number\":\"${DOC_PREFIX}-CONS\"}" \
    "${BASE_URL}/api/movements")
python3 - "$receipt" "$consume" <<'PY'
import json
import sys
from decimal import Decimal

receipt, consume = (json.loads(text) for text in sys.argv[1:])
assert receipt["type"] == "receipt" and receipt["allocations"] == []
assert receipt["current_stock"] == "18.000"
assert consume["type"] == "consume" and consume["allocations"]
assert consume["current_stock"] == "17.000"
assert receipt["sku"] == consume["sku"] == "OIL-001"
assert receipt["location"] == consume["location"] == "MS-01"
assert Decimal(receipt["current_stock"]) - Decimal(consume["current_stock"]) == 1
assert sum(Decimal(row["quantity"]) for row in consume["allocations"]) == 1
assert all(row["id"] > 0 and row["batch_id"] > 0 for row in consume["allocations"])
PY
duplicate=$(curl -sS -w '\n%{http_code}' -H 'Content-Type: application/json' \
    -d "{\"operation_date\":\"${OP_DATE}\",\"sku\":\"OIL-001\",\"location\":\"MS-01\",\"type\":\"consume\",\"quantity\":\"1.000\",\"doc_number\":\"${DOC_PREFIX}-CONS\"}" \
    "${BASE_URL}/api/movements")
[[ "${duplicate##*$'\n'}" == "409" ]]
python3 - "${duplicate%$'\n'*}" <<'PY'
import json
import sys

error = json.loads(sys.argv[1])
assert error["message"]
PY
curl -fsS "${BASE_URL}/api/movements?sku=OIL-001&location=MS-01&date_to=${OP_DATE}" | \
    python3 -c 'import json,sys; items=json.load(sys.stdin)["items"]; assert any(item["type"] == "consume" and item["allocations"] for item in items)'
before_rejections=$(curl -fsS "${BASE_URL}/api/movements?sku=OIL-001&location=MS-01&date_to=${OP_DATE}" | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["total"])')
for invalid in \
    "{\"operation_date\":\"${OP_DATE}\",\"sku\":\"CHECK-UNKNOWN-SKU\",\"location\":\"MS-01\",\"type\":\"consume\",\"quantity\":\"1.000\",\"doc_number\":\"${DOC_PREFIX}-UNKNOWN\"}" \
    "{\"operation_date\":\"${OP_DATE}\",\"sku\":\"OIL-001\",\"location\":\"CHECK-UNKNOWN-LOCATION\",\"type\":\"consume\",\"quantity\":\"1.000\",\"doc_number\":\"${DOC_PREFIX}-BADLOC\"}"; do
    reply=$(curl -sS -w '\n%{http_code}' -H 'Content-Type: application/json' -d "${invalid}" "${BASE_URL}/api/movements")
    [[ "${reply##*$'\n'}" == "404" ]]
done
for invalid in \
    "{\"operation_date\":\"${OP_DATE}\",\"sku\":\"OIL-001\",\"location\":\"MS-01\",\"type\":\"consume\",\"quantity\":\"0\",\"doc_number\":\"${DOC_PREFIX}-ZERO\"}" \
    "{\"operation_date\":\"${OP_DATE}\",\"sku\":\"OIL-001\",\"location\":\"MS-01\",\"type\":\"receipt\",\"quantity\":\"0\",\"doc_number\":\"${DOC_PREFIX}-ZEROR\",\"batch_number\":\"${DOC_PREFIX}-ZEROB\",\"unit_price\":\"100.00\"}" \
    "{\"operation_date\":\"${OP_DATE}\",\"sku\":\"OIL-001\",\"location\":\"MS-01\",\"type\":\"consume\",\"quantity\":\"1000000.000\",\"doc_number\":\"${DOC_PREFIX}-OVER\"}" \
    "{\"operation_date\":\"${FUTURE_DATE}\",\"sku\":\"OIL-001\",\"location\":\"MS-01\",\"type\":\"consume\",\"quantity\":\"1.000\",\"doc_number\":\"${DOC_PREFIX}-FUTURE\"}"; do
    reply=$(curl -sS -w '\n%{http_code}' -H 'Content-Type: application/json' -d "${invalid}" "${BASE_URL}/api/movements")
    [[ "${reply##*$'\n'}" == "422" ]]
done
after_rejections=$(curl -fsS "${BASE_URL}/api/movements?sku=OIL-001&location=MS-01&date_to=${OP_DATE}" | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["total"])')
[[ "${before_rejections}" == "${after_rejections}" ]]
curl -fsS "${BASE_URL}/api/stock/OIL-001?location=MS-01&as_of=${OP_DATE}" | python3 -c '
import json,sys
body=json.load(sys.stdin)
row=next(item for item in body["locations"] if item["location"] == "MS-01")
assert row["current_stock"] == "17.000"
'
curl -fsS -H 'Content-Type: application/json' \
    -d "{\"operation_date\":\"${AS_OF}\",\"sku\":\"DEMO-OIL\",\"location\":\"DEMO-MS-01\",\"type\":\"receipt\",\"quantity\":\"2.000\",\"doc_number\":\"DEMO-WEB-E2E-REC\",\"batch_number\":\"DEMO-WEB-E2E-BATCH\",\"unit_price\":\"100.00\"}" \
    "${BASE_URL}/api/movements" | python3 -c '
import json,sys
assert json.load(sys.stdin)["current_stock"] == "52.000"
'
curl -fsS "${BASE_URL}/api/demo/status" | python3 -c '
import json,sys
assert json.load(sys.stdin)["ready"] is True
'

# Повреждение данных на томе устраняется сбросом при следующем запуске app.
docker compose down >/dev/null
docker compose up -d db >/dev/null
docker compose exec -T db psql -U abs_user -d abs_inventory -c \
    "UPDATE items SET sku = 'DEMO-OIL-BROKEN' WHERE sku = 'DEMO-OIL';" >/dev/null
docker compose up -d app >/dev/null
docker compose up -d --no-deps web >/dev/null
for ((attempt = 0; attempt < 30; attempt++)); do
    if curl -fsS "${BASE_URL}/api/demo/status" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
curl -fsS "${BASE_URL}/api/demo/status" | python3 -c '
import json,sys
assert json.load(sys.stdin)["ready"] is True
'
curl -fsS "${BASE_URL}/api/stock?sku=DEMO-OIL&location=DEMO-MS-01" | python3 -c '
import json,sys
body=json.load(sys.stdin)
assert body["items"][0]["current_stock"] == "50.000"
'
