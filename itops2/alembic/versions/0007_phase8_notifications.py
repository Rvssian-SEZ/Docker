"""phase 8: notification subscriptions

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    event_type = sa.Enum(
        "checkout_performed",
        "checkin_performed",
        "warranty_expiring",
        "contract_renewal_due",
        "inventory_low_stock",
        name="core_notification_event",
    )

    op.create_table(
        "core_notification_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "event_type", name="uq_notification_sub_user_event"),
    )
    op.create_index("ix_core_notification_subscriptions_user_id", "core_notification_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_table("core_notification_subscriptions")
    sa.Enum(name="core_notification_event").drop(op.get_bind(), checkfirst=True)
