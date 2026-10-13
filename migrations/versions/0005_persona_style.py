"""паспорт образа модели: стиль модели и описание каждого варианта

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12 20:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('personas', sa.Column('style', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column('persona_photos', sa.Column('spec', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.drop_column('persona_photos', 'spec')
    op.drop_column('personas', 'style')
