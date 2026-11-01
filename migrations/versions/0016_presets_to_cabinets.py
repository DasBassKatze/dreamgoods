"""пресеты мастера — в его кабинет: общими (пресетами студии, видимыми всем и на сайте) остаются только готовые
пресеты сервиса и те, которыми уже снимают другие кабинеты

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-21 00:10:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None

# готовые пресеты сервиса (core/presets.DEFAULT_PRESETS) — остаются пресетами студии
DEFAULT_NAMES = ("Обувь — стандарт", "Одежда — на модели", "Товар для дома — лайфстайл", "Черновик — проверить идею")


def upgrade():
    conn = op.get_bind()
    names = ", ".join("'" + n.replace("'", "''") + "'" for n in DEFAULT_NAMES)
    conn.execute(sa.text(f"""
        WITH mc AS (
            SELECT DISTINCT ON (u.org_id) u.org_id, u.client_id
            FROM users u WHERE u.role = 'master' AND u.client_id IS NOT NULL
            ORDER BY u.org_id, u.id
        )
        UPDATE generation_presets gp SET client_id = mc.client_id
        FROM mc
        WHERE gp.org_id = mc.org_id AND gp.client_id IS NULL AND NOT gp.archived AND gp.name NOT IN ({names})
          AND NOT EXISTS (SELECT 1 FROM products p JOIN projects pr ON pr.id = p.project_id
                          WHERE p.preset_id = gp.id AND pr.client_id <> mc.client_id)
          AND NOT EXISTS (SELECT 1 FROM projects pr
                          WHERE pr.client_id <> mc.client_id AND (pr.settings ->> 'preset_id') = gp.id::text)
    """))


def downgrade():
    pass    # обратно не переносим: какие пресеты были общими, уже не известно
