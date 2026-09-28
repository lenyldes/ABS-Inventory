"""ORM-модели каталога: товары, объекты (филиалы) и поставщики."""

from sqlalchemy import Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Item(Base):
    """Товар с базовой единицей измерения и категорией."""

    __tablename__ = "items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(128), nullable=False, index=True)
    unit = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    supplier_conditions = relationship("SupplierCondition", back_populates="item")
    purchase_orders = relationship("PurchaseOrder", back_populates="item")
    batches = relationship("Batch", back_populates="item")
    movements = relationship("Movement", back_populates="item")
    stock_locks = relationship("StockLock", back_populates="item")


class Location(Base):
    """Объект (SPA-филиал) с уникальным кодом."""

    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    purchase_orders = relationship("PurchaseOrder", back_populates="location")
    batches = relationship("Batch", back_populates="location")
    movements = relationship("Movement", back_populates="location")
    stock_locks = relationship("StockLock", back_populates="location")


class Supplier(Base):
    """Справочник поставщиков."""

    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    supplier_conditions = relationship("SupplierCondition", back_populates="supplier")
    purchase_orders = relationship("PurchaseOrder", back_populates="supplier")
    movements = relationship("Movement", back_populates="supplier")
