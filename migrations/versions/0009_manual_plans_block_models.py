"""ручной план кадров и модель генерации на блок

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-12 23:45:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('generation_presets', sa.Column('plan_mode', sa.String(length=10), nullable=False, server_default='auto'))
    op.add_column('generation_presets', sa.Column('manual', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('generation_presets', sa.Column('block_models', postgresql.JSONB(), nullable=False,
                                                  server_default=sa.text("'{}'::jsonb")))
    op.add_column('frames', sa.Column('title', sa.String(length=80), nullable=False, server_default=''))
    op.add_column('frames', sa.Column('model', sa.String(length=120), nullable=False, server_default=''))


def downgrade():
    op.drop_column('frames', 'model')
    op.drop_column('frames', 'title')
    op.drop_column('generation_presets', 'block_models')
    op.drop_column('generation_presets', 'manual')
    op.drop_column('generation_presets', 'plan_mode')
