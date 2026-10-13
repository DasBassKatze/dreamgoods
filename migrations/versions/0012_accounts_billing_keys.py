"""многопользовательский сайт: вход по паролю, сессии, личные кабинеты, баланс клиентов, пул ключей Polza

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-13 19:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'polza_keys',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('org_id', sa.BigInteger(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(120), nullable=False, server_default=''),
        sa.Column('secret', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('shared', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column('users', sa.Column('password_hash', sa.Text(), nullable=False, server_default=''))
    op.add_column('users', sa.Column('client_id', sa.BigInteger(), sa.ForeignKey('clients.id', ondelete='SET NULL'), nullable=True))
    op.add_column('users', sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET role = 'master' WHERE role = 'owner'")
    op.create_table(
        'sessions',
        sa.Column('id', sa.String(64), primary_key=True),             # sha256 токена из cookie
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ip', sa.String(64), nullable=False, server_default=''),
        sa.Column('agent', sa.String(300), nullable=False, server_default=''),
    )
    op.add_column('clients', sa.Column('billing', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('clients', sa.Column('markup', sa.Float(), nullable=True))
    op.add_column('clients', sa.Column('key_id', sa.BigInteger(), sa.ForeignKey('polza_keys.id', ondelete='SET NULL'), nullable=True))
    op.create_table(
        'balance_ledger',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('client_id', sa.BigInteger(), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('project_id', sa.BigInteger(), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('kind', sa.String(20), nullable=False),               # topup | charge | adjust
        sa.Column('amount_rub', sa.Float(), nullable=False),             # + пополнение, − списание
        sa.Column('cost_rub', sa.Float(), nullable=False, server_default='0'),   # себестоимость (Polza) для списаний
        sa.Column('balance_after', sa.Float(), nullable=False, server_default='0'),
        sa.Column('what', sa.String(200), nullable=False, server_default=''),
        sa.Column('ref', sa.String(120), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_balance_ledger_created', 'balance_ledger', ['created_at'])
    op.add_column('generation_presets', sa.Column('client_id', sa.BigInteger(), sa.ForeignKey('clients.id', ondelete='CASCADE'),
                                                  nullable=True))


def downgrade():
    op.drop_column('generation_presets', 'client_id')
    op.drop_index('ix_balance_ledger_created', table_name='balance_ledger')
    op.drop_table('balance_ledger')
    op.drop_column('clients', 'key_id')
    op.drop_column('clients', 'markup')
    op.drop_column('clients', 'billing')
    op.drop_table('sessions')
    op.execute("UPDATE users SET role = 'owner' WHERE role = 'master'")
    for c in ('last_login_at', 'active', 'client_id', 'password_hash'):
        op.drop_column('users', c)
    op.drop_table('polza_keys')
