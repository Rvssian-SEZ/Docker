"""init

Revision ID: cf96b241efbe
Revises: 
Create Date: 2026-07-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'cf96b241efbe'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sub', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('department', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('groups', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_id', 'users', ['id'])
    op.create_index('ix_users_sub', 'users', ['sub'], unique=True)
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table(
        'equipment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('serial_number', sa.String(), nullable=True),
        sa.Column('asset_tag', sa.String(), nullable=True),
        sa.Column('status', sa.Enum('available', 'on_loan', 'maintenance', 'retired', name='equipmentstatus'), nullable=False),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_equipment_id', 'equipment', ['id'])
    op.create_index('ix_equipment_name', 'equipment', ['name'])
    op.create_index('ix_equipment_asset_tag', 'equipment', ['asset_tag'], unique=True)

    op.create_table(
        'it_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('asset_tag', sa.String(), nullable=True),
        sa.Column('category', sa.Enum('laptop', 'desktop', 'monitor', 'phone', 'tablet', 'printer', 'networking', 'server', 'peripheral', 'other', name='assetcategory'), nullable=True),
        sa.Column('manufacturer', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('serial_number', sa.String(), nullable=True),
        sa.Column('status', sa.Enum('available', 'assigned', 'maintenance', 'retired', 'lost', name='assetstatus'), nullable=False),
        sa.Column('assigned_user_id', sa.Integer(), nullable=True),
        sa.Column('purchase_date', sa.Date(), nullable=True),
        sa.Column('warranty_expiry', sa.Date(), nullable=True),
        sa.Column('purchase_price', sa.String(), nullable=True),
        sa.Column('supplier', sa.String(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['assigned_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_it_assets_id', 'it_assets', ['id'])
    op.create_index('ix_it_assets_name', 'it_assets', ['name'])
    op.create_index('ix_it_assets_asset_tag', 'it_assets', ['asset_tag'], unique=True)
    op.create_index('ix_it_assets_assigned_user_id', 'it_assets', ['assigned_user_id'])

    op.create_table(
        'lending_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('equipment_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('lent_at', sa.DateTime(), nullable=False),
        sa.Column('due_at', sa.DateTime(), nullable=True),
        sa.Column('returned_at', sa.DateTime(), nullable=True),
        sa.Column('lent_by_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id']),
        sa.ForeignKeyConstraint(['lent_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lending_records_id', 'lending_records', ['id'])
    op.create_index('ix_lending_records_equipment_id', 'lending_records', ['equipment_id'])
    op.create_index('ix_lending_records_user_id', 'lending_records', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_lending_records_user_id', table_name='lending_records')
    op.drop_index('ix_lending_records_equipment_id', table_name='lending_records')
    op.drop_index('ix_lending_records_id', table_name='lending_records')
    op.drop_table('lending_records')
    op.drop_index('ix_it_assets_assigned_user_id', table_name='it_assets')
    op.drop_index('ix_it_assets_asset_tag', table_name='it_assets')
    op.drop_index('ix_it_assets_name', table_name='it_assets')
    op.drop_index('ix_it_assets_id', table_name='it_assets')
    op.drop_table('it_assets')
    op.execute('DROP TYPE IF EXISTS assetstatus')
    op.execute('DROP TYPE IF EXISTS assetcategory')
    op.drop_index('ix_equipment_asset_tag', table_name='equipment')
    op.drop_index('ix_equipment_name', table_name='equipment')
    op.drop_index('ix_equipment_id', table_name='equipment')
    op.drop_table('equipment')
    op.execute('DROP TYPE IF EXISTS equipmentstatus')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_username', table_name='users')
    op.drop_index('ix_users_sub', table_name='users')
    op.drop_index('ix_users_id', table_name='users')
    op.drop_table('users')
