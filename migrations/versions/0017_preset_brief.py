"""пресет: пожелания к генерации (режим «Авто»)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-21 01:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('generation_presets', sa.Column('brief', sa.Text(), nullable=False, server_default=''))


def downgrade():
    op.drop_column('generation_presets', 'brief')
