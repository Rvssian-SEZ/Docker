"""phase 9: v1 import schema (departments, user fields, import tracking)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "core_departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("core_companies.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", "company_id", name="uq_department_name_company"),
    )
    op.create_index("ix_core_departments_name", "core_departments", ["name"])
    op.create_index("ix_core_departments_company_id", "core_departments", ["company_id"])

    op.add_column("core_users", sa.Column("phone", sa.String(50)))
    op.add_column("core_users", sa.Column("job_title", sa.String(200)))
    op.add_column("core_users", sa.Column("department_id", sa.Integer(), sa.ForeignKey("core_departments.id")))
    op.create_index("ix_core_users_department_id", "core_users", ["department_id"])

    batch_status = sa.Enum("running", "completed", "failed", name="core_import_batch_status")
    op.create_table(
        "core_v1_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("started_by", sa.Integer(), sa.ForeignKey("core_users.id"), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", batch_status, nullable=False, server_default="running"),
    )

    row_outcome = sa.Enum("created", "skipped", "flagged", "failed", name="core_import_row_outcome")
    op.create_table(
        "core_v1_import_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("core_v1_import_batches.id"), nullable=False),
        sa.Column("is_dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("v1_table", sa.String(100), nullable=False),
        sa.Column("v1_id", sa.Integer(), nullable=False),
        sa.Column("v2_entity_type", sa.String(50), nullable=False),
        sa.Column("v2_entity_id", sa.Integer()),
        sa.Column("outcome", row_outcome, nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_v1_import_rows_batch_id", "core_v1_import_rows", ["batch_id"])
    op.create_index("ix_core_v1_import_rows_v1_table", "core_v1_import_rows", ["v1_table"])
    op.create_index("ix_core_v1_import_rows_v1_id", "core_v1_import_rows", ["v1_id"])
    op.create_index(
        "uq_v1_import_row_created_once",
        "core_v1_import_rows",
        ["v1_table", "v1_id"],
        unique=True,
        postgresql_where=sa.text("outcome = 'created' AND is_dry_run = false"),
    )


def downgrade() -> None:
    op.drop_table("core_v1_import_rows")
    sa.Enum(name="core_import_row_outcome").drop(op.get_bind(), checkfirst=True)
    op.drop_table("core_v1_import_batches")
    sa.Enum(name="core_import_batch_status").drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_core_users_department_id", table_name="core_users")
    op.drop_column("core_users", "department_id")
    op.drop_column("core_users", "job_title")
    op.drop_column("core_users", "phone")
    op.drop_table("core_departments")
