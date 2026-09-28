"""initial_domain_schema

Revision ID: 2df052e2bbd9
Revises:
Create Date: 2026-09-28 11:18:59.426381

"""

from collections.abc import Sequence

from app.database_schema.amendments_tables import create_amendments_tables, drop_amendments_tables
from app.database_schema.catalog_tables import create_catalog_tables, drop_catalog_tables
from app.database_schema.inventory_tables import create_inventory_tables, drop_inventory_tables
from app.database_schema.movement_tables import create_movement_tables, drop_movement_tables
from app.database_schema.procurement_tables import (
    create_procurement_tables,
    drop_procurement_tables,
)

# revision identifiers, used by Alembic.
revision: str = "2df052e2bbd9"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    create_catalog_tables()
    create_procurement_tables()
    create_inventory_tables()
    create_movement_tables()
    create_amendments_tables()


def downgrade() -> None:
    """Downgrade schema."""
    drop_amendments_tables()
    drop_movement_tables()
    drop_inventory_tables()
    drop_procurement_tables()
    drop_catalog_tables()
