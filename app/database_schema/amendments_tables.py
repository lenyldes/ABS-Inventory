"""Создание и удаление таблиц аудита и исправлений (amendments, versions)."""

import sqlalchemy as sa

from alembic import op


def create_amendments_tables() -> None:
    """Создаёт таблицы наборов исправлений, операций и аудита версий."""
    op.create_table(
        "amendment_sets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("amendment_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version_signature", sa.String(length=128), nullable=False),
        sa.Column("preview_data", sa.JSON(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('preview', 'applied', 'rejected')", name="chk_amendment_sets_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_amendment_sets_amendment_id"), "amendment_sets", ["amendment_id"], unique=True
    )
    op.create_index(op.f("ix_amendment_sets_status"), "amendment_sets", ["status"], unique=False)

    op.create_table(
        "amendment_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("amendment_set_id", sa.Integer(), nullable=False),
        sa.Column("movement_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("action IN ('update', 'cancel')", name="chk_amendment_entries_action"),
        sa.CheckConstraint("expected_version >= 1", name="chk_amendment_entries_expected_version"),
        sa.ForeignKeyConstraint(["amendment_set_id"], ["amendment_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movement_id"], ["movements.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_amendment_entries_amendment_set_id"),
        "amendment_entries",
        ["amendment_set_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_amendment_entries_movement_id"), "amendment_entries", ["movement_id"], unique=False
    )

    op.create_table(
        "movement_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movement_id", sa.Integer(), nullable=False),
        sa.Column("version_num", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('create', 'update', 'cancel')", name="chk_movement_versions_action"
        ),
        sa.CheckConstraint("version_num >= 1", name="chk_movement_versions_version_num"),
        sa.ForeignKeyConstraint(["movement_id"], ["movements.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "movement_id", "version_num", name="uq_movement_versions_movement_version"
        ),
    )
    op.create_index(
        op.f("ix_movement_versions_movement_id"), "movement_versions", ["movement_id"], unique=False
    )


def drop_amendments_tables() -> None:
    """Удаляет таблицы аудита и исправлений."""
    op.drop_index(op.f("ix_movement_versions_movement_id"), table_name="movement_versions")
    op.drop_table("movement_versions")
    op.drop_index(op.f("ix_amendment_entries_movement_id"), table_name="amendment_entries")
    op.drop_index(op.f("ix_amendment_entries_amendment_set_id"), table_name="amendment_entries")
    op.drop_table("amendment_entries")
    op.drop_index(op.f("ix_amendment_sets_status"), table_name="amendment_sets")
    op.drop_index(op.f("ix_amendment_sets_amendment_id"), table_name="amendment_sets")
    op.drop_table("amendment_sets")
