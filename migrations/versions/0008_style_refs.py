"""референсы оформления: фото-примеры стиля и привязка к товарам

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-12 23:15:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'style_refs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('client_id', sa.BigInteger(), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('blocks', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_style_refs_client_id', 'style_refs', ['client_id'])
    op.create_table(
        'style_ref_photos',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('style_ref_id', sa.BigInteger(), sa.ForeignKey('style_refs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('asset_id', sa.UUID(), sa.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_style_ref_photos_style_ref_id', 'style_ref_photos', ['style_ref_id'])
    op.add_column('products', sa.Column('style_ref_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_products_style_ref', 'products', 'style_refs', ['style_ref_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_products_style_ref', 'products', type_='foreignkey')
    op.drop_column('products', 'style_ref_id')
    op.drop_index('ix_style_ref_photos_style_ref_id', table_name='style_ref_photos')
    op.drop_table('style_ref_photos')
    op.drop_index('ix_style_refs_client_id', table_name='style_refs')
    op.drop_table('style_refs')
