"""заявки на пополнение баланса (до подключения онлайн-оплаты)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-17 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'topup_requests',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('client_id', sa.BigInteger(), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount_rub', sa.Float(), nullable=False),
        sa.Column('bonus_rub', sa.Float(), nullable=False, server_default='0'),
        sa.Column('method', sa.String(20), nullable=False, server_default='card'),
        sa.Column('status', sa.String(20), nullable=False, server_default='new'),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('topup_requests')
