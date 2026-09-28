#!/usr/bin/env bash
set -euo pipefail

# Сквозной интеграционный сценарий: preview -> confirm -> history -> остатки и связанные поставки
PROJECT_NAME="abs_amendments_e2e_test"
POSTGRES_PORT="5443"
PORT="8013"

cleanup() {
    COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

echo "=== [1/4] Запуск изолированного Compose-проекта ==="
cleanup
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
echo "Стек успешно запущен."

echo "=== [2/4] Подготовка тестового заказа поставщику ==="
PO_INFO=$(COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose exec -T app python -c '
from datetime import date
from decimal import Decimal
from app.models.catalog import Item, Location, Supplier
from app.models.procurement import PurchaseOrder
from app.core.database import get_session_factory

f = get_session_factory()
s = f()
item = s.query(Item).filter_by(sku="E2E-OIL-01").first()
if not item:
    item = Item(sku="E2E-OIL-01", name="Масло E2E", category="Масла", unit="л")
    s.add(item)
loc = s.query(Location).filter_by(code="E2E-LOC-01").first()
if not loc:
    loc = Location(code="E2E-LOC-01", name="SPA E2E")
    s.add(loc)
supp = s.query(Supplier).filter_by(supplier_id="E2E-SUP-01").first()
if not supp:
    supp = Supplier(supplier_id="E2E-SUP-01", name="Поставщик E2E")
    s.add(supp)
s.flush()
po = PurchaseOrder(
    item_id=item.id,
    location_id=loc.id,
    supplier_id=supp.id,
    doc_number="PO-E2E-99",
    expected_date=date(2026, 10, 1),
    expected_qty=Decimal("20.000"),
    received_qty=Decimal("0.000"),
    pending_qty=Decimal("20.000"),
    status="pending",
)
s.add(po)
s.commit()
print(f"{item.sku} {loc.code} {po.id}")
s.close()
')

read -r SKU LOC PO_ID <<< "${PO_INFO}"
echo "Создан тестовый заказ: ${SKU}, ${LOC}, PO ID: ${PO_ID}"

echo "=== [3/4] Выполнение HTTP-сценария: preview -> confirm -> history -> остатки ==="
python3 scripts/test_amendments_e2e.py "http://localhost:${PORT}" "${SKU}" "${LOC}" "${PO_ID}"

echo "=== [4/4] Проверка пересчёта связанного заказа поставщику ==="
COMPOSE_PROJECT_NAME="${PROJECT_NAME}" docker compose exec -T app python -c "
from decimal import Decimal
from app.models.procurement import PurchaseOrder
from app.core.database import get_session_factory

f = get_session_factory()
s = f()
po = s.get(PurchaseOrder, ${PO_ID})
assert po.received_qty == Decimal('16.000'), f'Expected 16.000, got {po.received_qty}'
assert po.pending_qty == Decimal('4.000'), f'Expected 4.000, got {po.pending_qty}'
assert po.status == 'partially_received', f'Expected partially_received, got {po.status}'
s.close()
"
echo "Связанный заказ поставщику пересчитан корректно (received=16, pending=4)."
