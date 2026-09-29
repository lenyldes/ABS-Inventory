"""Декларативные определения складских движений демонстрационного набора."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

# Опорное движение для определения as_of набора
DEMO_BASE_RECEIPT_DOC: str = "DEMO-REC-OIL-BASE"
DEMO_BASE_RECEIPT_OFFSET: int = -100


@dataclass(frozen=True)
class DemoMovementDef:
    """Определение складского движения со смещением даты относительно as_of."""

    sku: str
    location_code: str
    movement_type: str  # "receipt" или "consume"
    offset_days: int
    quantity: Decimal
    doc_number: str
    batch_number: str | None = None
    expiry_offset_days: int | None = None
    unit_price: Decimal | None = None
    supplier_id: str | None = None

    def resolve_date(self, as_of: date) -> date:
        """Вычисляет фактическую дату операции от as_of."""
        return as_of + timedelta(days=self.offset_days)

    def resolve_expiry_date(self, as_of: date) -> date | None:
        """Вычисляет дату срока годности от as_of."""
        if self.expiry_offset_days is None:
            return None
        return as_of + timedelta(days=self.expiry_offset_days)


def _generate_oil_consumes() -> list[DemoMovementDef]:
    """Генерирует 90 ежедневных расходов масла по 1 единице на дни -89..0."""
    consumes: list[DemoMovementDef] = []
    for day_offset in range(-89, 1):
        seq = day_offset - (-89) + 1
        consumes.append(
            DemoMovementDef(
                sku="DEMO-OIL",
                location_code="DEMO-MS-01",
                movement_type="consume",
                offset_days=day_offset,
                quantity=Decimal("1.000"),
                doc_number=f"DEMO-CONS-OIL-{seq}",
            )
        )
    return consumes


def build_demo_movement_definitions() -> list[DemoMovementDef]:
    """Формирует полный список определений движений демонабора."""
    definitions: list[DemoMovementDef] = [
        # 1. DEMO-OIL: приход 140 на -100
        DemoMovementDef(
            sku="DEMO-OIL",
            location_code="DEMO-MS-01",
            movement_type="receipt",
            offset_days=DEMO_BASE_RECEIPT_OFFSET,
            quantity=Decimal("140.000"),
            doc_number=DEMO_BASE_RECEIPT_DOC,
            batch_number="DEMO-BATCH-OIL",
            expiry_offset_days=180,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-MAIN",
        ),
        # 90 ежедневных списаний масла
        *_generate_oil_consumes(),
        # 2. DEMO-DEFICIT (на DEMO-MS-02): приход 95 на -100, расход 90 на -1
        DemoMovementDef(
            sku="DEMO-DEFICIT",
            location_code="DEMO-MS-02",
            movement_type="receipt",
            offset_days=-100,
            quantity=Decimal("95.000"),
            doc_number="DEMO-REC-DEFICIT",
            batch_number="DEMO-BATCH-DEFICIT",
            expiry_offset_days=180,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-MAIN",
        ),
        DemoMovementDef(
            sku="DEMO-DEFICIT",
            location_code="DEMO-MS-02",
            movement_type="consume",
            offset_days=-1,
            quantity=Decimal("90.000"),
            doc_number="DEMO-CONS-DEFICIT-1",
        ),
        # 3. DEMO-EXPIRY: приход 40 на -20 с годностью +5, расход 10 на -5
        DemoMovementDef(
            sku="DEMO-EXPIRY",
            location_code="DEMO-MS-01",
            movement_type="receipt",
            offset_days=-20,
            quantity=Decimal("40.000"),
            doc_number="DEMO-REC-EXPIRY",
            batch_number="DEMO-BATCH-EXPIRY",
            expiry_offset_days=5,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-MAIN",
        ),
        DemoMovementDef(
            sku="DEMO-EXPIRY",
            location_code="DEMO-MS-01",
            movement_type="consume",
            offset_days=-5,
            quantity=Decimal("10.000"),
            doc_number="DEMO-CONS-EXPIRY-1",
        ),
        # 4. DEMO-EXPIRED: приход 10 на -20 с годностью -1, без расхода
        DemoMovementDef(
            sku="DEMO-EXPIRED",
            location_code="DEMO-MS-01",
            movement_type="receipt",
            offset_days=-20,
            quantity=Decimal("10.000"),
            doc_number="DEMO-REC-EXPIRED",
            batch_number="DEMO-BATCH-EXPIRED",
            expiry_offset_days=-1,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-MAIN",
        ),
        # 5. DEMO-IDLE: приход 10 на -120 с годностью +180, без расхода
        DemoMovementDef(
            sku="DEMO-IDLE",
            location_code="DEMO-MS-01",
            movement_type="receipt",
            offset_days=-120,
            quantity=Decimal("10.000"),
            doc_number="DEMO-REC-IDLE",
            batch_number="DEMO-BATCH-IDLE",
            expiry_offset_days=180,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-MAIN",
        ),
        # 6. DEMO-SHORT (на DEMO-MS-02): приход 20 на -10, расход 1 на -5
        DemoMovementDef(
            sku="DEMO-SHORT",
            location_code="DEMO-MS-02",
            movement_type="receipt",
            offset_days=-10,
            quantity=Decimal("20.000"),
            doc_number="DEMO-REC-SHORT",
            batch_number="DEMO-BATCH-SHORT",
            expiry_offset_days=180,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-MAIN",
        ),
        DemoMovementDef(
            sku="DEMO-SHORT",
            location_code="DEMO-MS-02",
            movement_type="consume",
            offset_days=-5,
            quantity=Decimal("1.000"),
            doc_number="DEMO-CONS-SHORT-1",
        ),
        # 7. DEMO-NOPRICE: приход 95 на -100 от запасного DEMO-SUP-ALT, расход 90 на -1
        DemoMovementDef(
            sku="DEMO-NOPRICE",
            location_code="DEMO-MS-01",
            movement_type="receipt",
            offset_days=-100,
            quantity=Decimal("95.000"),
            doc_number="DEMO-REC-NOPRICE",
            batch_number="DEMO-BATCH-NOPRICE",
            expiry_offset_days=180,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-ALT",
        ),
        DemoMovementDef(
            sku="DEMO-NOPRICE",
            location_code="DEMO-MS-01",
            movement_type="consume",
            offset_days=-1,
            quantity=Decimal("90.000"),
            doc_number="DEMO-CONS-NOPRICE-1",
        ),
        # 8. DEMO-NOLEAD: приход 95 на -100, расход 90 на -1
        DemoMovementDef(
            sku="DEMO-NOLEAD",
            location_code="DEMO-MS-01",
            movement_type="receipt",
            offset_days=-100,
            quantity=Decimal("95.000"),
            doc_number="DEMO-REC-NOLEAD",
            batch_number="DEMO-BATCH-NOLEAD",
            expiry_offset_days=180,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-MAIN",
        ),
        DemoMovementDef(
            sku="DEMO-NOLEAD",
            location_code="DEMO-MS-01",
            movement_type="consume",
            offset_days=-1,
            quantity=Decimal("90.000"),
            doc_number="DEMO-CONS-NOLEAD-1",
        ),
        # 9. DEMO-INCOMING: приход 95 на -100, расход 90 на -1
        DemoMovementDef(
            sku="DEMO-INCOMING",
            location_code="DEMO-MS-01",
            movement_type="receipt",
            offset_days=-100,
            quantity=Decimal("95.000"),
            doc_number="DEMO-REC-INCOMING",
            batch_number="DEMO-BATCH-INCOMING",
            expiry_offset_days=180,
            unit_price=Decimal("100.00"),
            supplier_id="DEMO-SUP-MAIN",
        ),
        DemoMovementDef(
            sku="DEMO-INCOMING",
            location_code="DEMO-MS-01",
            movement_type="consume",
            offset_days=-1,
            quantity=Decimal("90.000"),
            doc_number="DEMO-CONS-INCOMING-1",
        ),
    ]
    return definitions


DEMO_MOVEMENTS: list[DemoMovementDef] = build_demo_movement_definitions()

DEMO_MOVEMENT_DOC_NUMBERS: set[str] = {m.doc_number for m in DEMO_MOVEMENTS}
DEMO_BATCH_NUMBERS: set[str] = {m.batch_number for m in DEMO_MOVEMENTS if m.batch_number}
