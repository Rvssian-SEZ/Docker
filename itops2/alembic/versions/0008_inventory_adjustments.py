"""inventory adjustment ledger (post-phase-8 refinement)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "core_inventory_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("core_inventory_items.id"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("adjusted_by", sa.Integer(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("adjusted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_inventory_adjustments_item_id", "core_inventory_adjustments", ["item_id"])
    op.create_index("ix_core_inventory_adjustments_adjusted_at", "core_inventory_adjustments", ["adjusted_at"])


def downgrade() -> None:
    op.drop_table("core_inventory_adjustments")
