"""пресеты генерации: качество и план кадров

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12 20:10:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'generation_presets',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('org_id', sa.BigInteger(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('quality', sa.String(length=20), nullable=False, server_default='standard'),
        sa.Column('custom', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('plan', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_generation_presets_org_id', 'generation_presets', ['org_id'])
    op.add_column('products', sa.Column('preset_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_products_preset', 'products', 'generation_presets', ['preset_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_products_preset', 'products', type_='foreignkey')
    op.drop_column('products', 'preset_id')
    op.drop_index('ix_generation_presets_org_id', table_name='generation_presets')
    op.drop_table('generation_presets')
