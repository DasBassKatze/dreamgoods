"""Совместимость с ранней Dev-GPT, где номер 0013 использовался другой миграцией.

Никакие старые данные не удаляются. На обычной dev-ui это пустой шаг.
"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0013_gpt_bridge"
down_revision = "0013"
branch_labels = depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("topup_requests"):
        spec = spec_from_file_location("original_topups", Path(__file__).with_name("0013_topup_requests.py"))
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        module.upgrade()


def downgrade():
    pass  # таблица принадлежит исходной миграции 0013
