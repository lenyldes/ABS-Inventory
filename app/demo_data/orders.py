"""Декларативные определения ожидаемых заказов демонстрационного набора."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class DemoOrderDef:
    """Определение ожидаемого заказа (PurchaseOrder) со смещением от as_of."""

    doc_number: str
    sku: str
    location_code: str
    supplier_id: str
    offset_days: int
    expected_qty: Decimal
    received_qty: Decimal
    pending_qty: Decimal
    unit_price: Decimal | None
    status: str = "pending"

    def resolve_expected_date(self, as_of: date) -> date:
        """Вычисляет дату ожидаемой поставки от as_of."""
        return as_of + timedelta(days=self.offset_days)


DEMO_ORDERS: list[DemoOrderDef] = [
    DemoOrderDef(
        doc_number="DEMO-PO-INCOMING",
        sku="DEMO-INCOMING",
        location_code="DEMO-MS-01",
        supplier_id="DEMO-SUP-MAIN",
        offset_days=1,
        expected_qty=Decimal("20.000"),
        received_qty=Decimal("0.000"),
        pending_qty=Decimal("20.000"),
        unit_price=Decimal("100.00"),
        status="pending",
    ),
]

DEMO_ORDER_DOC_NUMBERS: set[str] = {o.doc_number for o in DEMO_ORDERS}
