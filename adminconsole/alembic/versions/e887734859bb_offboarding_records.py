"""offboarding records

Revision ID: e887734859bb
Revises: 8ed80e0a4e79
Create Date: 2026-09-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e887734859bb'
down_revision: Union[str, None] = '8ed80e0a4e79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('offboarding_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sam', sa.String(length=150), nullable=False),
    sa.Column('display_name', sa.String(length=255), nullable=True),
    sa.Column('dn', sa.String(length=500), nullable=False),
    sa.Column('initiated_by', sa.String(length=150), nullable=False),
    sa.Column('initiated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('disable_ok', sa.Boolean(), nullable=False),
    sa.Column('reset_password_ok', sa.Boolean(), nullable=False),
    sa.Column('removed_groups_json', sa.Text(), nullable=False),
    sa.Column('mailbox_converted', sa.Boolean(), nullable=False),
    sa.Column('mailbox_converted_by', sa.String(length=150), nullable=True),
    sa.Column('mailbox_converted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('licenses_removed', sa.Boolean(), nullable=False),
    sa.Column('licenses_removed_by', sa.String(length=150), nullable=True),
    sa.Column('licenses_removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_by', sa.String(length=150), nullable=True),
    sa.Column('completed_reason', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_offboarding_records_sam'), 'offboarding_records', ['sam'], unique=False)
    op.create_index(op.f('ix_offboarding_records_initiated_at'), 'offboarding_records', ['initiated_at'], unique=False)
    op.create_index(op.f('ix_offboarding_records_completed_at'), 'offboarding_records', ['completed_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_offboarding_records_completed_at'), table_name='offboarding_records')
    op.drop_index(op.f('ix_offboarding_records_initiated_at'), table_name='offboarding_records')
    op.drop_index(op.f('ix_offboarding_records_sam'), table_name='offboarding_records')
    op.drop_table('offboarding_records')
