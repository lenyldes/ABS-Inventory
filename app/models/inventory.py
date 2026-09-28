"""ORM-модели склада: партии, движения, распределения и блокировки остатка."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Batch(Base):
    """Учётная партия поступления с фиксацией цены и срока годности."""

    __tablename__ = "batches"

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
    batch_number = Column(String(128), nullable=False)
    receipt_date = Column(Date, nullable=False, index=True)
    expiry_date = Column(Date, nullable=True, index=True)
    unit_price = Column(Numeric(12, 2), nullable=False)
    receipt_doc_number = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    item = relationship("Item", back_populates="batches")
    location = relationship("Location", back_populates="batches")
    allocations = relationship("MovementAllocation", back_populates="batch")
    movements = relationship(
        "Movement",
        back_populates="batch",
        foreign_keys="Movement.batch_id",
    )

    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="chk_batches_unit_price"),
        Index(
            "idx_batches_fefo",
            "expiry_date",
            "receipt_date",
            "created_at",
            "id",
        ),
    )


class Movement(Base):
    """Складское движение (приход, расход, списание, возврат, корректировка)."""

    __tablename__ = "movements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    operation_date = Column(Date, nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
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
    type = Column(String(32), nullable=False, index=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    doc_number = Column(String(64), nullable=False, index=True)
    batch_id = Column(
        Integer,
        ForeignKey("batches.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    reason = Column(Text, nullable=True)
    parent_movement_id = Column(
        Integer,
        ForeignKey("movements.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    parent_allocation_id = Column(
        Integer,
        ForeignKey(
            "movement_allocations.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_movements_parent_allocation_id",
        ),
        nullable=True,
        index=True,
    )
    purchase_order_id = Column(
        Integer,
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    status = Column(String(32), default="active", nullable=False, index=True)
    current_version = Column(Integer, default=1, nullable=False)

    item = relationship("Item", back_populates="movements")
    location = relationship("Location", back_populates="movements")
    batch = relationship(
        "Batch",
        back_populates="movements",
        foreign_keys=[batch_id],
    )
    parent_movement = relationship(
        "Movement",
        remote_side=[id],
        foreign_keys=[parent_movement_id],
    )
    parent_allocation = relationship(
        "MovementAllocation",
        foreign_keys=[parent_allocation_id],
        post_update=True,
    )
    purchase_order = relationship("PurchaseOrder", back_populates="movements")
    supplier = relationship("Supplier", back_populates="movements")
    allocations = relationship(
        "MovementAllocation",
        back_populates="movement",
        foreign_keys="MovementAllocation.movement_id",
        cascade="all, delete-orphan",
    )
    versions = relationship(
        "MovementVersion",
        back_populates="movement",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('receipt', 'consume', 'writeoff', 'return', 'correction')",
            name="chk_movements_type",
        ),
        CheckConstraint(
            "status IN ('active', 'cancelled')",
            name="chk_movements_status",
        ),
        CheckConstraint(
            "quantity != 0",
            name="chk_movements_quantity_not_zero",
        ),
        CheckConstraint(
            "current_version >= 1",
            name="chk_movements_current_version",
        ),
        Index(
            "uq_movements_location_doc_active",
            "location_id",
            "doc_number",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class MovementAllocation(Base):
    """Строка распределения движения расхода/возврата по конкретной партии."""

    __tablename__ = "movement_allocations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movement_id = Column(
        Integer,
        ForeignKey("movements.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    batch_id = Column(
        Integer,
        ForeignKey("batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    movement = relationship(
        "Movement",
        back_populates="allocations",
        foreign_keys=[movement_id],
    )
    batch = relationship(
        "Batch",
        back_populates="allocations",
        foreign_keys=[batch_id],
    )

    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="chk_movement_allocations_quantity",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="chk_movement_allocations_unit_price",
        ),
    )


class StockLock(Base):
    """Служебная сущность для сериализации транзакций по паре (товар, объект)."""

    __tablename__ = "stock_locks"

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
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    item = relationship("Item", back_populates="stock_locks")
    location = relationship("Location", back_populates="stock_locks")

    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "location_id",
            name="uq_stock_locks_item_location",
        ),
    )
