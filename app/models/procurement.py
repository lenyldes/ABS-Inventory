"""ORM-модели закупок: закупочные условия и ожидаемые поставки (заказы)."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class SupplierCondition(Base):
    """Закупочные условия для пары «товар + поставщик»."""

    __tablename__ = "supplier_conditions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    lead_time_days = Column(Integer, nullable=False)
    package_size = Column(Numeric(12, 3), nullable=False)
    min_order_qty = Column(Numeric(12, 3), nullable=False)
    estimated_price = Column(Numeric(12, 2), nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    item = relationship("Item", back_populates="supplier_conditions")
    supplier = relationship("Supplier", back_populates="supplier_conditions")

    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "supplier_id",
            name="uq_supplier_conditions_item_supplier",
        ),
        Index(
            "uq_item_primary_supplier",
            "item_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
        ),
        CheckConstraint(
            "lead_time_days >= 1",
            name="chk_supplier_conditions_lead_time_days",
        ),
        CheckConstraint(
            "package_size > 0",
            name="chk_supplier_conditions_package_size",
        ),
        CheckConstraint(
            "min_order_qty > 0",
            name="chk_supplier_conditions_min_order_qty",
        ),
        CheckConstraint(
            "estimated_price IS NULL OR estimated_price >= 0",
            name="chk_supplier_conditions_estimated_price",
        ),
    )


class PurchaseOrder(Base):
    """Ожидаемая поставка (заказ поставщику)."""

    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(
        Integer,
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    doc_number = Column(String(64), nullable=False, index=True)
    expected_date = Column(Date, nullable=False, index=True)
    expected_qty = Column(Numeric(12, 3), nullable=False)
    received_qty = Column(Numeric(12, 3), default=0, nullable=False)
    pending_qty = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=True)
    status = Column(String(32), default="pending", nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    item = relationship("Item", back_populates="purchase_orders")
    location = relationship("Location", back_populates="purchase_orders")
    supplier = relationship("Supplier", back_populates="purchase_orders")
    movements = relationship("Movement", back_populates="purchase_order")

    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "doc_number",
            name="uq_purchase_orders_location_doc",
        ),
        CheckConstraint(
            "expected_qty > 0",
            name="chk_purchase_orders_expected_qty",
        ),
        CheckConstraint(
            "received_qty >= 0",
            name="chk_purchase_orders_received_qty",
        ),
        CheckConstraint(
            "pending_qty >= 0",
            name="chk_purchase_orders_pending_qty",
        ),
        CheckConstraint(
            "received_qty <= expected_qty",
            name="chk_purchase_orders_received_le_expected",
        ),
        CheckConstraint(
            "status IN ('pending', 'delayed', 'partially_received', 'received', 'cancelled')",
            name="chk_purchase_orders_status",
        ),
        CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name="chk_purchase_orders_unit_price",
        ),
    )
