"""модель клиента: группы товаров, которые снимаются на ней

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-13 01:10:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('personas', sa.Column('groups', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade():
    op.drop_column('personas', 'groups')
