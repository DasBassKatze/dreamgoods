"""согласия и документы, подтверждение почты (регистрация на сайте)

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-22 19:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    # учётные записи, заведённые до регистрации на сайте, завёл мастер — почта считается подтверждённой
    op.execute("UPDATE users SET email_verified_at = created_at")
    op.create_table(
        'email_tokens',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(20), nullable=False, server_default='verify'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'legal_documents',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('org_id', sa.BigInteger(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False, server_default=''),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('author_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('org_id', 'kind', 'version'),
    )
    op.create_table(
        'consents',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('org_id', sa.BigInteger(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('client_id', sa.BigInteger(), sa.ForeignKey('clients.id', ondelete='SET NULL'), nullable=True),
        sa.Column('email', sa.String(200), nullable=False, server_default=''),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('doc_version', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('granted', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('source', sa.String(20), nullable=False, server_default=''),
        sa.Column('subject', sa.String(300), nullable=False, server_default=''),
        sa.Column('ref', sa.String(120), nullable=False, server_default=''),
        sa.Column('ip', sa.String(64), nullable=False, server_default=''),
        sa.Column('agent', sa.String(300), nullable=False, server_default=''),
    )
    op.create_index('ix_consents_user_kind', 'consents', ['user_id', 'kind'])


def downgrade():
    op.drop_index('ix_consents_user_kind', 'consents')
    op.drop_table('consents')
    op.drop_table('legal_documents')
    op.drop_table('email_tokens')
    op.drop_column('users', 'email_verified_at')
