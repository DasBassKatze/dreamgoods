"""Точные суммы и ограничения активных заданий поверх dev-ui 0.8.0."""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = depends_on = None

MONEY = {
    "clients": ("balance_rub", "markup"),
    "topup_requests": ("amount_rub", "bonus_rub"),
    "balance_ledger": ("amount_rub", "cost_rub", "balance_after"),
    "persona_photos": ("cost_rub",), "product_profiles": ("cost_rub",),
    "generations": ("cost_rub",), "qc_checks": ("cost_rub",),
    "usage_ledger": ("amount_rub",), "import_sessions": ("cost_rub",),
}


def upgrade():
    for table, columns in MONEY.items():
        for column in columns:
            op.alter_column(table, column, type_=sa.Numeric(18, 6),
                            postgresql_using=f"{column}::numeric(18,6)")
    for key, condition in (
        ("frame_id", "frame_id IS NOT NULL"),
        ("product_id", "product_id IS NOT NULL AND kind = 'profile'"),
    ):
        op.execute(f"""WITH duplicates AS (
            SELECT id, row_number() OVER (PARTITION BY {key} ORDER BY id) AS n
            FROM jobs WHERE {condition} AND status IN ('queued','running','cancelling'))
            UPDATE jobs SET status='error', error='Дублирующее задание остановлено миграцией 0019', finished_at=now()
            WHERE id IN (SELECT id FROM duplicates WHERE n > 1)""")
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_active_frame ON jobs (frame_id)
        WHERE frame_id IS NOT NULL AND status IN ('queued','running','cancelling')""")
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_active_profile ON jobs (product_id)
        WHERE kind = 'profile' AND status IN ('queued','running','cancelling')""")


def downgrade():
    op.drop_index("uq_jobs_active_profile", table_name="jobs")
    op.drop_index("uq_jobs_active_frame", table_name="jobs")
    for table, columns in MONEY.items():
        for column in columns:
            op.alter_column(table, column, type_=sa.Float(), postgresql_using=f"{column}::double precision")
