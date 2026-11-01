"""журнал модерации: остановленное запрещённое содержание

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-20 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'moderation_events',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('org_id', sa.BigInteger(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('client_id', sa.BigInteger(), sa.ForeignKey('clients.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('project_id', sa.BigInteger(), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('frame_id', sa.BigInteger(), sa.ForeignKey('frames.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('where', sa.String(60), nullable=False, server_default=''),
        sa.Column('category', sa.String(30), nullable=False, server_default=''),
        sa.Column('excerpt', sa.Text(), nullable=False, server_default=''),
        sa.Column('action', sa.String(20), nullable=False, server_default='blocked'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('moderation_events')
