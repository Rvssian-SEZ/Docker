"""initial core schema

Revision ID: 0001
Revises:
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

role_name = sa.Enum("admin", "manager", "technician", "viewer", name="core_role_name")
auth_source = sa.Enum("local", "oidc", "ldap", name="core_auth_source")


def upgrade() -> None:
    op.create_table(
        "core_companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_core_companies_name", "core_companies", ["name"], unique=True)

    op.create_table(
        "core_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", role_name, nullable=False, unique=True),
        sa.Column("description", sa.String(255)),
    )

    op.create_table(
        "core_role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("core_roles.id"), nullable=False),
        sa.Column("permission", sa.String(100), nullable=False),
        sa.UniqueConstraint("role_id", "permission", name="uq_role_permission"),
    )
    op.create_index("ix_core_role_permissions_role_id", "core_role_permissions", ["role_id"])
    op.create_index("ix_core_role_permissions_permission", "core_role_permissions", ["permission"])

    op.create_table(
        "core_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(150), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("display_name", sa.String(255)),
        sa.Column("auth_source", auth_source, nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("core_roles.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("core_companies.id")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_breakglass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_core_users_username", "core_users", ["username"], unique=True)
    op.create_index("ix_core_users_email", "core_users", ["email"])
    op.create_index("ix_core_users_company_id", "core_users", ["company_id"])

    op.create_table(
        "core_settings",
        sa.Column("key", sa.String(150), primary_key=True),
        sa.Column("value", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "core_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("core_users.id")),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(50)),
        sa.Column("detail", sa.Text()),
    )
    for col in ("at", "user_id", "action", "entity_type", "entity_id"):
        op.create_index(f"ix_core_audit_log_{col}", "core_audit_log", [col])


def downgrade() -> None:
    op.drop_table("core_audit_log")
    op.drop_table("core_settings")
    op.drop_table("core_users")
    op.drop_table("core_role_permissions")
    op.drop_table("core_roles")
    op.drop_table("core_companies")
    auth_source.drop(op.get_bind(), checkfirst=True)
    role_name.drop(op.get_bind(), checkfirst=True)
