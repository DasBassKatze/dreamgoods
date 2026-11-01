"""Durable payments, run budgets, precise money, atomic queue admission."""
from alembic import op
import sqlalchemy as sa
revision = "0013"
down_revision = "0012"
branch_labels = depends_on = None

MONEY = {
    "clients": ("balance_rub", "markup"),
    "balance_ledger": ("amount_rub", "cost_rub", "balance_after"),
    "persona_photos": ("cost_rub",), "product_profiles": ("cost_rub",),
    "generations": ("cost_rub",), "qc_checks": ("cost_rub",),
    "usage_ledger": ("amount_rub",), "import_sessions": ("cost_rub",),
}

def upgrade():
    for table, columns in MONEY.items():
        for column in columns:
            op.alter_column(table, column, type_=sa.Numeric(18, 4),
                postgresql_using=f"{column}::numeric(18,4)")
    op.add_column("clients", sa.Column("parallel_limit", sa.Integer(), nullable=False, server_default="2"))
    op.create_table("generation_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_rub", sa.Numeric(18,4)), sa.Column("retry_budget_rub", sa.Numeric(18,4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_generation_runs_project_id", "generation_runs", ["project_id"])
    op.add_column("jobs", sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("generation_runs.id")))
    op.create_index("ix_jobs_run_id", "jobs", ["run_id"])
    op.add_column("generations", sa.Column("billing_operation_id", sa.String(36)))
    op.create_table("billing_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.BigInteger(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("generation_runs.id")),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("external_id", sa.String(120), nullable=False),
        *[sa.Column(n, sa.Numeric(18,4), nullable=False) for n in ("reserved_rub", "charged_rub", "cost_rub", "markup")],
        sa.Column("billable", sa.Boolean(), nullable=False), sa.Column("is_retry", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for c in ("client_id", "project_id", "run_id", "status"):
        op.create_index("ix_billing_operations_" + c, "billing_operations", [c])
    # Existing duplicates are kept in history; only the oldest remains active.
    op.execute("""WITH duplicates AS (
        SELECT id, row_number() OVER (PARTITION BY frame_id ORDER BY id) AS n FROM jobs
        WHERE frame_id IS NOT NULL AND status IN ('queued','running','cancelling'))
        UPDATE jobs SET status='error', error='duplicate active job retired by migration 0013', finished_at=now()
        WHERE id IN (SELECT id FROM duplicates WHERE n > 1)""")
    op.execute("""WITH duplicates AS (
        SELECT id, row_number() OVER (PARTITION BY product_id ORDER BY id) AS n FROM jobs
        WHERE kind='profile' AND product_id IS NOT NULL AND status IN ('queued','running','cancelling'))
        UPDATE jobs SET status='error', error='duplicate active profile retired by migration 0013', finished_at=now()
        WHERE id IN (SELECT id FROM duplicates WHERE n > 1)""")
    op.create_index("uq_jobs_active_frame", "jobs", ["frame_id"], unique=True,
        postgresql_where=sa.text("frame_id IS NOT NULL AND status IN ('queued','running','cancelling')"))
    op.create_index("uq_jobs_active_profile", "jobs", ["product_id"], unique=True,
        postgresql_where=sa.text("kind = 'profile' AND status IN ('queued','running','cancelling')"))


def downgrade():
    op.drop_index("uq_jobs_active_profile", table_name="jobs")
    op.drop_index("uq_jobs_active_frame", table_name="jobs")
    op.drop_table("billing_operations")
    op.drop_column("generations", "billing_operation_id")
    op.drop_column("jobs", "run_id")
    op.drop_table("generation_runs")
    op.drop_column("clients", "parallel_limit")
    for table, columns in MONEY.items():
        for column in columns:
            op.alter_column(table, column, type_=sa.Float(), postgresql_using=f"{column}::double precision")
