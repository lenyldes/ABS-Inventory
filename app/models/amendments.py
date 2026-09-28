"""ORM-модели аудита и наборов исправлений движений."""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class AmendmentSet(Base):
    """Набор связанных исправлений для предварительного просмотра и применения."""

    __tablename__ = "amendment_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    amendment_id = Column(String(64), unique=True, nullable=False, index=True)
    reason = Column(Text, nullable=False)
    status = Column(String(32), default="preview", nullable=False, index=True)
    version_signature = Column(String(128), nullable=False)
    preview_data = Column(JSON, nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    entries = relationship(
        "AmendmentEntry",
        back_populates="amendment_set",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('preview', 'applied', 'rejected')",
            name="chk_amendment_sets_status",
        ),
    )


class AmendmentEntry(Base):
    """Строка операции внутри набора исправлений."""

    __tablename__ = "amendment_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    amendment_set_id = Column(
        Integer,
        ForeignKey("amendment_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    movement_id = Column(
        Integer,
        ForeignKey("movements.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action = Column(String(32), nullable=False)
    expected_version = Column(Integer, nullable=False)
    details = Column(JSON, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    amendment_set = relationship("AmendmentSet", back_populates="entries")
    movement = relationship("Movement")

    __table_args__ = (
        CheckConstraint(
            "action IN ('update', 'cancel')",
            name="chk_amendment_entries_action",
        ),
        CheckConstraint(
            "expected_version >= 1",
            name="chk_amendment_entries_expected_version",
        ),
    )


class MovementVersion(Base):
    """Аудит версий изменений складского движения."""

    __tablename__ = "movement_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    movement_id = Column(
        Integer,
        ForeignKey("movements.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_num = Column(Integer, nullable=False)
    action = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    movement = relationship("Movement", back_populates="versions")

    __table_args__ = (
        UniqueConstraint(
            "movement_id",
            "version_num",
            name="uq_movement_versions_movement_version",
        ),
        CheckConstraint(
            "version_num >= 1",
            name="chk_movement_versions_version_num",
        ),
        CheckConstraint(
            "action IN ('create', 'update', 'cancel')",
            name="chk_movement_versions_action",
        ),
    )
