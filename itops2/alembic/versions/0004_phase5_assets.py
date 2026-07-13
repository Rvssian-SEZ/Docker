"""phase 5: assets, checkouts, attachments

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "core_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_tag", sa.String(50), nullable=False),
        sa.Column("serial", sa.String(200)),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("core_models.id"), nullable=False),
        sa.Column("status_label_id", sa.Integer(), sa.ForeignKey("core_status_labels.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("core_companies.id")),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("core_locations.id")),
        sa.Column("purchase_date", sa.Date()),
        sa.Column("purchase_cost", sa.Numeric(14, 2)),
        sa.Column("purchase_currency", sa.String(3), sa.ForeignKey("core_currencies.code")),
        sa.Column("warranty_months", sa.Integer()),
        sa.Column("depreciation_months_override", sa.Integer()),
        sa.Column("eol_months_override", sa.Integer()),
        sa.Column("notes", sa.Text()),
        sa.Column("checked_out_to_user_id", sa.Integer(), sa.ForeignKey("core_users.id")),
        sa.Column("checked_out_to_location_id", sa.Integer(), sa.ForeignKey("core_locations.id")),
        sa.Column("checked_out_to_asset_id", sa.Integer(), sa.ForeignKey("core_assets.id")),
        sa.Column("checked_out_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("asset_tag", name="uq_asset_tag"),
        sa.CheckConstraint(
            "num_nonnulls(checked_out_to_user_id, checked_out_to_location_id, checked_out_to_asset_id) <= 1",
            name="ck_asset_checkout_target_singular",
        ),
        sa.CheckConstraint(
            "checked_out_to_asset_id IS NULL OR checked_out_to_asset_id <> id",
            name="ck_asset_no_self_checkout",
        ),
        sa.CheckConstraint(
            "(checked_out_at IS NULL) = "
            "(num_nonnulls(checked_out_to_user_id, checked_out_to_location_id, checked_out_to_asset_id) = 0)",
            name="ck_asset_checkout_at_matches_target",
        ),
    )
    op.create_index("ix_core_assets_asset_tag", "core_assets", ["asset_tag"])
    op.create_index("ix_core_assets_serial", "core_assets", ["serial"])
    op.create_index("ix_core_assets_model_id", "core_assets", ["model_id"])
    op.create_index("ix_core_assets_status_label_id", "core_assets", ["status_label_id"])
    op.create_index("ix_core_assets_company_id", "core_assets", ["company_id"])
    op.create_index("ix_core_assets_location_id", "core_assets", ["location_id"])
    op.create_index("ix_core_assets_purchase_date", "core_assets", ["purchase_date"])
    op.create_index("ix_core_assets_checked_out_to_user_id", "core_assets", ["checked_out_to_user_id"])
    op.create_index("ix_core_assets_checked_out_to_location_id", "core_assets", ["checked_out_to_location_id"])
    op.create_index("ix_core_assets_checked_out_to_asset_id", "core_assets", ["checked_out_to_asset_id"])

    op.create_table(
        "core_checkouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("core_assets.id"), nullable=False),
        sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("core_users.id")),
        sa.Column("target_location_id", sa.Integer(), sa.ForeignKey("core_locations.id")),
        sa.Column("target_asset_id", sa.Integer(), sa.ForeignKey("core_assets.id")),
        sa.Column(
            "status_label_id_at_checkout", sa.Integer(), sa.ForeignKey("core_status_labels.id"), nullable=False
        ),
        sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_out_by", sa.Integer(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("expected_checkin_at", sa.Date()),
        sa.Column("checked_in_at", sa.DateTime(timezone=True)),
        sa.Column("checked_in_by", sa.Integer(), sa.ForeignKey("core_users.id")),
        sa.Column("checkin_status_label_id", sa.Integer(), sa.ForeignKey("core_status_labels.id")),
        sa.Column("notes", sa.Text()),
        sa.CheckConstraint(
            "num_nonnulls(target_user_id, target_location_id, target_asset_id) <= 1",
            name="ck_checkout_target_singular",
        ),
    )
    op.create_index("ix_core_checkouts_asset_id", "core_checkouts", ["asset_id"])
    op.create_index("ix_core_checkouts_target_user_id", "core_checkouts", ["target_user_id"])
    op.create_index("ix_core_checkouts_target_location_id", "core_checkouts", ["target_location_id"])
    op.create_index("ix_core_checkouts_target_asset_id", "core_checkouts", ["target_asset_id"])
    # Partial unique index: at most one OPEN (checked_in_at IS NULL) checkout per asset.
    op.execute(
        "CREATE UNIQUE INDEX uq_checkout_one_open_per_asset ON core_checkouts (asset_id) "
        "WHERE checked_in_at IS NULL"
    )

    op.create_table(
        "core_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(50), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(150)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stored_filename", name="uq_attachment_stored_filename"),
    )
    op.create_index("ix_core_attachments_entity", "core_attachments", ["entity_type", "entity_id"])
    op.create_index("ix_core_attachments_uploaded_by", "core_attachments", ["uploaded_by"])
    op.create_index("ix_core_attachments_uploaded_at", "core_attachments", ["uploaded_at"])


def downgrade() -> None:
    op.drop_table("core_attachments")
    op.execute("DROP INDEX IF EXISTS uq_checkout_one_open_per_asset")
    op.drop_table("core_checkouts")
    op.drop_table("core_assets")
