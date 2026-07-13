"""phase 4a: core lookups (locations, manufacturers, categories, status labels, models)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

status_type = sa.Enum("deployable", "deployed", "pending", "archived", name="core_status_type")


def upgrade() -> None:
    op.create_table(
        "core_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_locations_name", "core_locations", ["name"], unique=True)

    op.create_table(
        "core_manufacturers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_manufacturers_name", "core_manufacturers", ["name"], unique=True)

    op.create_table(
        "core_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_categories_name", "core_categories", ["name"], unique=True)

    op.create_table(
        "core_status_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("status_type", status_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_status_labels_name", "core_status_labels", ["name"], unique=True)

    op.create_table(
        "core_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("manufacturer_id", sa.Integer(), sa.ForeignKey("core_manufacturers.id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("core_categories.id"), nullable=False),
        sa.Column("depreciation_months", sa.Integer()),
        sa.Column("eol_months", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", "manufacturer_id", name="uq_model_name_manufacturer"),
    )
    op.create_index("ix_core_models_name", "core_models", ["name"])
    op.create_index("ix_core_models_manufacturer_id", "core_models", ["manufacturer_id"])
    op.create_index("ix_core_models_category_id", "core_models", ["category_id"])


def downgrade() -> None:
    op.drop_table("core_models")
    op.drop_table("core_status_labels")
    status_type.drop(op.get_bind(), checkfirst=True)
    op.drop_table("core_categories")
    op.drop_table("core_manufacturers")
    op.drop_table("core_locations")
