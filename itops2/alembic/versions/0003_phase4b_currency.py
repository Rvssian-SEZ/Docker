"""phase 4b: currencies + exchange rates

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "core_currencies",
        sa.Column("code", sa.String(3), primary_key=True),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "core_exchange_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_currency", sa.String(3), sa.ForeignKey("core_currencies.code"), nullable=False),
        sa.Column("to_currency", sa.String(3), sa.ForeignKey("core_currencies.code"), nullable=False),
        sa.Column("rate", sa.Numeric(18, 6), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "from_currency", "to_currency", "effective_date", name="uq_exchange_rate_from_to_date"
        ),
    )
    op.create_index("ix_core_exchange_rates_from_currency", "core_exchange_rates", ["from_currency"])
    op.create_index("ix_core_exchange_rates_to_currency", "core_exchange_rates", ["to_currency"])
    op.create_index("ix_core_exchange_rates_effective_date", "core_exchange_rates", ["effective_date"])


def downgrade() -> None:
    op.drop_table("core_exchange_rates")
    op.drop_table("core_currencies")
