"""offboarding cancel

Revision ID: fc0834196905
Revises: e887734859bb
Create Date: 2026-09-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fc0834196905'
down_revision: Union[str, None] = 'e887734859bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('offboarding_records', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('offboarding_records', sa.Column('cancelled_by', sa.String(length=150), nullable=True))
    op.add_column('offboarding_records', sa.Column('cancelled_reason', sa.Text(), nullable=True))
    op.create_index(op.f('ix_offboarding_records_cancelled_at'), 'offboarding_records', ['cancelled_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_offboarding_records_cancelled_at'), table_name='offboarding_records')
    op.drop_column('offboarding_records', 'cancelled_reason')
    op.drop_column('offboarding_records', 'cancelled_by')
    op.drop_column('offboarding_records', 'cancelled_at')
