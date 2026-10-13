"""модели клиента (personas)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12 19:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'personas',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('client_id', sa.BigInteger(), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('brief', sa.Text(), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='generated'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('consent', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_personas_client_id', 'personas', ['client_id'])
    op.create_table(
        'persona_photos',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('persona_id', sa.BigInteger(), sa.ForeignKey('personas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('asset_id', sa.UUID(), sa.ForeignKey('assets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='photo'),
        sa.Column('view', sa.String(length=40), nullable=False, server_default=''),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_rub', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_persona_photos_persona_id', 'persona_photos', ['persona_id'])
    op.add_column('products', sa.Column('persona_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_products_persona', 'products', 'personas', ['persona_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_products_persona', 'products', type_='foreignkey')
    op.drop_column('products', 'persona_id')
    op.drop_index('ix_persona_photos_persona_id', table_name='persona_photos')
    op.drop_table('persona_photos')
    op.drop_index('ix_personas_client_id', table_name='personas')
    op.drop_table('personas')
