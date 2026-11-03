"""Референс отдельного метода ручного плана."""
from alembic import op
import sqlalchemy as sa
revision = '0021'
down_revision = '0020'
branch_labels = depends_on = None

def upgrade():
    op.add_column('frames', sa.Column('shot_reference_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_frames_shot_reference', 'frames', 'style_refs', ['shot_reference_id'], ['id'], ondelete='SET NULL')

def downgrade():
    op.drop_constraint('fk_frames_shot_reference', 'frames', type_='foreignkey')
    op.drop_column('frames', 'shot_reference_id')
