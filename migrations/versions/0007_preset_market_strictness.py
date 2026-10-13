"""пресет: профиль площадки и строгость проверки

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12 20:30:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('generation_presets', sa.Column('market', postgresql.JSONB(), nullable=False,
                                                  server_default=sa.text("'{}'::jsonb")))
    op.add_column('generation_presets', sa.Column('strictness', sa.String(length=20), nullable=False, server_default='normal'))


def downgrade():
    op.drop_column('generation_presets', 'strictness')
    op.drop_column('generation_presets', 'market')
