"""phase 7: licenses & contracts + inventory

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    contract_type = sa.Enum("license", "contract", "subscription", name="core_contract_type")

    op.create_table(
        "core_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("contract_type", contract_type, nullable=False),
        sa.Column("vendor", sa.String(200)),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("core_companies.id")),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("core_locations.id")),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("cost", sa.Numeric(14, 2)),
        sa.Column("currency", sa.String(3), sa.ForeignKey("core_currencies.code")),
        sa.Column("renewal_period_months", sa.Integer()),
        sa.Column("auto_renews", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_contracts_name", "core_contracts", ["name"])
    op.create_index("ix_core_contracts_company_id", "core_contracts", ["company_id"])
    op.create_index("ix_core_contracts_location_id", "core_contracts", ["location_id"])
    op.create_index("ix_core_contracts_end_date", "core_contracts", ["end_date"])

    op.create_table(
        "core_contract_assets",
        sa.Column(
            "contract_id", sa.Integer(),
            sa.ForeignKey("core_contracts.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column(
            "asset_id", sa.Integer(),
            sa.ForeignKey("core_assets.id", ondelete="CASCADE"), primary_key=True,
        ),
    )

    op.create_table(
        "core_inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("core_categories.id"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("core_locations.id")),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_quantity", sa.Integer()),
        sa.Column("unit_cost", sa.Numeric(14, 2)),
        sa.Column("currency", sa.String(3), sa.ForeignKey("core_currencies.code")),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_inventory_items_name", "core_inventory_items", ["name"])
    op.create_index("ix_core_inventory_items_category_id", "core_inventory_items", ["category_id"])
    op.create_index("ix_core_inventory_items_location_id", "core_inventory_items", ["location_id"])


def downgrade() -> None:
    op.drop_table("core_inventory_items")
    op.drop_table("core_contract_assets")
    op.drop_table("core_contracts")
    sa.Enum(name="core_contract_type").drop(op.get_bind(), checkfirst=True)
