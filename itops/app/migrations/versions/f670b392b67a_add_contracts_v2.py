"""add contracts v2

Revision ID: f670b392b67a
Revises: cf96b241efbe
Create Date: 2026-07-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f670b392b67a'
down_revision: Union[str, None] = 'cf96b241efbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'contracts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('contract_type', sa.Enum('saas', 'support', 'vendor', name='contracttype'), nullable=False),
        sa.Column('status', sa.Enum('active', 'expiring_soon', 'expired', 'cancelled', name='contractstatus'), nullable=False),
        sa.Column('vendor_name', sa.String(), nullable=True),
        sa.Column('vendor_contact_name', sa.String(), nullable=True),
        sa.Column('vendor_contact_email', sa.String(), nullable=True),
        sa.Column('vendor_contact_phone', sa.String(), nullable=True),
        sa.Column('cost', sa.String(), nullable=True),
        sa.Column('billing_cycle', sa.Enum('monthly', 'quarterly', 'annual', 'one_time', name='billingcycle'), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('renewal_date', sa.Date(), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_contracts_id', 'contracts', ['id'])
    op.create_index('ix_contracts_name', 'contracts', ['name'])
    op.create_index('ix_contracts_owner_id', 'contracts', ['owner_id'])

    # Drop legacy helpdesk tables if they exist (only present on original install)
    op.execute('DROP TABLE IF EXISTS hd_ticket_updates CASCADE')
    op.execute('DROP TABLE IF EXISTS hd_tickets CASCADE')
    op.execute('DROP TABLE IF EXISTS alembic_version_helpdesk CASCADE')


def downgrade() -> None:
    op.drop_index('ix_contracts_owner_id', table_name='contracts')
    op.drop_index('ix_contracts_name', table_name='contracts')
    op.drop_index('ix_contracts_id', table_name='contracts')
    op.drop_table('contracts')
    op.execute('DROP TYPE IF EXISTS contracttype')
    op.execute('DROP TYPE IF EXISTS contractstatus')
    op.execute('DROP TYPE IF EXISTS billingcycle')
