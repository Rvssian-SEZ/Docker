"""phase 6: maintenance records + printer details extension table

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    maintenance_type = sa.Enum("repair", "maintenance", "upgrade", name="core_maintenance_type")

    op.create_table(
        "core_maintenance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("core_assets.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("maintenance_type", maintenance_type, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cost", sa.Numeric(14, 2)),
        sa.Column("currency", sa.String(3), sa.ForeignKey("core_currencies.code")),
        sa.Column("performed_by", sa.String(200)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_maintenance_asset_id", "core_maintenance", ["asset_id"])
    op.create_index("ix_core_maintenance_date", "core_maintenance", ["date"])

    op.create_table(
        "core_printer_details",
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("core_assets.id"), primary_key=True),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("hostname", sa.String(255)),
        sa.Column("consumable_notes", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("core_printer_details")
    op.drop_table("core_maintenance")
    sa.Enum(name="core_maintenance_type").drop(op.get_bind(), checkfirst=True)
