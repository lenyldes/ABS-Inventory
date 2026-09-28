"""Сквозной интеграционный сценарий: preview -> confirm -> history -> остатки и поставки."""

import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from decimal import Decimal


def _http(method: str, url: str, data: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, json.loads(raw) if raw else {}


def main() -> None:
    base_url = sys.argv[1].rstrip("/")
    sku = sys.argv[2]
    loc = sys.argv[3]
    po_id = int(sys.argv[4])

    print(f"Запуск сквозного сценария для {sku} на {loc}, PO #{po_id}...")

    # 1. Регистрация первичного прихода по заказу (10.000)
    today_str = date.today().isoformat()
    expiry_str = (date.today() + timedelta(days=180)).isoformat()
    code, rec = _http(
        "POST",
        f"{base_url}/api/movements",
        {
            "operation_date": today_str,
            "sku": sku,
            "location": loc,
            "type": "receipt",
            "quantity": "10.000",
            "doc_number": "E2E-REC-01",
            "batch_number": "E2E-BATCH-01",
            "expiry_date": expiry_str,
            "unit_price": "100.00",
            "purchase_order_id": po_id,
        },
    )
    assert code == 201, f"Ошибка создания прихода: {code}, {rec}"
    rec_id = rec["id"]

    # 2. Регистрация расхода (4.000)
    code, cons = _http(
        "POST",
        f"{base_url}/api/movements",
        {
            "operation_date": today_str,
            "sku": sku,
            "location": loc,
            "type": "consume",
            "quantity": "4.000",
            "doc_number": "E2E-CONS-01",
        },
    )
    assert code == 201, f"Ошибка создания расхода: {code}, {cons}"

    # 3. Проверка остатка до исправлений: 10 - 4 = 6
    code, stock = _http("GET", f"{base_url}/api/stock?sku={sku}&location={loc}")
    assert code == 200 and Decimal(str(stock["items"][0]["current_stock"])) == Decimal("6.000")

    # 4. Preview: увеличение прихода до 16.000
    code, prev = _http(
        "POST",
        f"{base_url}/api/amendments/preview",
        {
            "reason": "Уточнение накладной E2E",
            "operations": [
                {
                    "movement_id": rec_id,
                    "action": "update",
                    "expected_version": 1,
                    "fields": {"quantity": "16.000"},
                }
            ],
        },
    )
    assert code == 200 and prev["can_apply"] is True, f"Preview failed: {prev}"
    preview_id = prev["preview_id"]
    signature = prev["version_signature"]
    impact = prev["stock_impact"][0]
    assert Decimal(impact["current_stock_before"]) == Decimal("6.000")
    assert Decimal(impact["current_stock_after"]) == Decimal("12.000")

    # 5. Проверяем, что склад после preview НЕ изменился
    code, stock_check = _http("GET", f"{base_url}/api/stock?sku={sku}&location={loc}")
    assert Decimal(str(stock_check["items"][0]["current_stock"])) == Decimal("6.000")

    # 6. Confirm: подтверждаем набор
    code, conf = _http(
        "POST",
        f"{base_url}/api/amendments/confirm",
        {
            "preview_id": preview_id,
            "version_signature": signature,
            "reason": "Уточнение накладной E2E",
        },
    )
    assert code == 200 and conf["status"] == "applied", f"Confirm failed: {conf}"

    # 7. Проверка истории версий: GET /api/movements/{id}/history
    code, hist = _http("GET", f"{base_url}/api/movements/{rec_id}/history")
    assert code == 200 and len(hist["versions"]) == 2
    v2 = hist["versions"][1]
    assert v2["version_num"] == 2 and v2["action"] == "update"
    assert v2["reason"] == "Уточнение накладной E2E"
    assert v2["changes"]["quantity"]["old"] == "10.000"
    assert v2["changes"]["quantity"]["new"] == "16.000"

    # 8. Проверка остатка после confirm: 16 - 4 = 12
    code, stock_after = _http("GET", f"{base_url}/api/stock?sku={sku}&location={loc}")
    assert Decimal(str(stock_after["items"][0]["current_stock"])) == Decimal("12.000")
    print("Сквозной сценарий успешно проверен!")


if __name__ == "__main__":
    main()
