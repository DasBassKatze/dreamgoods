"""тарифы клиентов: тариф и срок у кабинета, тариф в заявке на пополнение

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-18 12:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013_gpt_bridge'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clients', sa.Column('plan', sa.String(20), nullable=False, server_default='start'))
    op.add_column('clients', sa.Column('plan_until', sa.DateTime(timezone=True), nullable=True))
    # уже работающие кабинеты с оплатой через баланс не теряют возможностей: им — «Агентство» без срока
    op.execute("UPDATE clients SET plan = 'agency' WHERE billing")
    op.add_column('topup_requests', sa.Column('plan', sa.String(20), nullable=False, server_default=''))
    op.add_column('topup_requests', sa.Column('months', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('topup_requests', 'months')
    op.drop_column('topup_requests', 'plan')
    op.drop_column('clients', 'plan_until')
    op.drop_column('clients', 'plan')

