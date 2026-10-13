"""правка готового фото по промпту и дозагрузка оплаченных задач Polza

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-13 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    # что просили изменить (для правок); пусто — обычная генерация
    op.add_column('generations', sa.Column('instruction', sa.Text(), nullable=False, server_default=''))
    # с какой версии кадра делалась правка
    op.add_column('generations', sa.Column('source_id', sa.BigInteger(), nullable=True))
    op.create_index('ix_generations_pending', 'generations', ['status'], postgresql_where=sa.text("status = 'pending'"))


def downgrade():
    op.drop_index('ix_generations_pending', table_name='generations')
    op.drop_column('generations', 'source_id')
    op.drop_column('generations', 'instruction')
