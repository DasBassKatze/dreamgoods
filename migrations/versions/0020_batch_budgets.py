"""Бюджеты партий и резервы отдельных платных запросов."""
from alembic import op
import sqlalchemy as sa
revision='0020'
down_revision='0019'
branch_labels=depends_on=None

def upgrade():
    op.create_table('budget_batches',
        sa.Column('id',sa.BigInteger(),primary_key=True),
        sa.Column('project_id',sa.BigInteger(),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('title',sa.String(200),nullable=False,server_default='Генерация'),
        sa.Column('budget_rub',sa.Numeric(18,6)),sa.Column('retry_budget_rub',sa.Numeric(18,6)),
        sa.Column('state',sa.String(20),nullable=False,server_default='active'),
        sa.Column('pause_reason',sa.Text(),nullable=False,server_default=''),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.drop_index('uq_jobs_active_frame',table_name='jobs')
    op.drop_index('uq_jobs_active_profile',table_name='jobs')
    op.create_index('uq_jobs_active_frame','jobs',['frame_id'],unique=True,
        postgresql_where=sa.text("frame_id IS NOT NULL AND status IN ('queued','running','cancelling','paused')"))
    op.create_index('uq_jobs_active_profile','jobs',['product_id'],unique=True,
        postgresql_where=sa.text("kind='profile' AND status IN ('queued','running','cancelling','paused')"))
    op.create_index('ix_budget_batches_project_id','budget_batches',['project_id'])
    op.add_column('jobs',sa.Column('batch_id',sa.BigInteger(),sa.ForeignKey('budget_batches.id',ondelete='SET NULL')))
    op.create_index('ix_jobs_batch_id','jobs',['batch_id'])
    op.add_column('generations',sa.Column('paid_operation_id',sa.String(36)))
    op.create_table('paid_operations',
        sa.Column('id',sa.String(36),primary_key=True),
        *[sa.Column(n,sa.BigInteger(),sa.ForeignKey(t,ondelete=action),nullable=nullable) for n,t,action,nullable in (
            ('client_id','clients.id','CASCADE',False),('project_id','projects.id','CASCADE',False),
            ('job_id','jobs.id','SET NULL',True),('batch_id','budget_batches.id','SET NULL',True),
            ('product_id','products.id','SET NULL',True),('frame_id','frames.id','SET NULL',True))],
        sa.Column('kind',sa.String(20),nullable=False),sa.Column('model',sa.String(120),nullable=False,server_default=''),
        sa.Column('status',sa.String(20),nullable=False,server_default='reserved'),
        sa.Column('external_id',sa.String(120),nullable=False,server_default=''),
        *[sa.Column(n,sa.Numeric(18,6),nullable=False,server_default='0') for n in ('reserved_rub','charged_rub','cost_rub')],
        sa.Column('markup',sa.Numeric(18,6),nullable=False,server_default='1'),
        sa.Column('billable',sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column('is_retry',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('note',sa.Text(),nullable=False,server_default=''),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    for col in ('client_id','project_id','job_id','batch_id','status'):
        op.create_index('ix_paid_operations_'+col,'paid_operations',[col])
    adopt_pending()

def downgrade():
    op.drop_index('uq_jobs_active_frame',table_name='jobs')
    op.drop_index('uq_jobs_active_profile',table_name='jobs')
    op.create_index('uq_jobs_active_frame','jobs',['frame_id'],unique=True,
        postgresql_where=sa.text("frame_id IS NOT NULL AND status IN ('queued','running','cancelling')"))
    op.create_index('uq_jobs_active_profile','jobs',['product_id'],unique=True,
        postgresql_where=sa.text("kind='profile' AND status IN ('queued','running','cancelling')"))
    op.drop_table('paid_operations')
    op.drop_column('generations','paid_operation_id')
    op.drop_column('jobs','batch_id')
    op.drop_table('budget_batches')


def adopt_pending():
    """Незавершённые задачи старой версии тоже занимают резерв; старое списание не повторяется."""
    from decimal import Decimal
    conn=op.get_bind()
    inspector=sa.inspect(conn)
    legacy=inspector.has_table('billing_operations') and any(c['name']=='billing_operation_id' for c in inspector.get_columns('generations'))
    old_column='g.billing_operation_id' if legacy else 'NULL'
    rows=conn.execute(sa.text(f'''SELECT g.id,g.frame_id,g.job_id,g.model,g.external_id,g.cost_rub,
        p.id AS product_id,p.project_id,c.id AS client_id,c.billing,c.markup,o.settings,j.payload,
        {old_column} AS old_id
        FROM generations g JOIN frames f ON f.id=g.frame_id JOIN products p ON p.id=f.product_id
        JOIN projects pr ON pr.id=p.project_id JOIN clients c ON c.id=pr.client_id
        JOIN organizations o ON o.id=c.org_id LEFT JOIN jobs j ON j.id=g.job_id
        WHERE g.status='pending' AND g.paid_operation_id IS NULL''')).mappings().all()
    for row in rows:
        old=conn.execute(sa.text('SELECT * FROM billing_operations WHERE id=:id'),{'id':row['old_id']}).mappings().first() if legacy and row['old_id'] else None
        billable=bool(old['billable']) if old else bool(row['billing'] and not (row['payload'] or {}).get('by_master'))
        raw_markup=old['markup'] if old else row['markup'] if row['markup'] is not None else (row['settings'] or {}).get('markup',1)
        markup=Decimal(str(raw_markup)) if billable else Decimal(1)
        settled=bool(old and old['status']=='settled')
        reserved=Decimal(str(old['reserved_rub'])) if old else Decimal('62.50')*markup
        oid='legacy-'+str(row['id'])
        conn.execute(sa.text('''INSERT INTO paid_operations
            (id,client_id,project_id,job_id,product_id,frame_id,kind,model,status,external_id,
             reserved_rub,charged_rub,cost_rub,markup,billable,is_retry,note)
            VALUES (:id,:client,:project,:job,:product,:frame,'generation',:model,:status,:external,
                    :reserved,:charged,:cost,:markup,:billable,false,:note)'''),
            dict(id=oid,client=row['client_id'],project=row['project_id'],job=row['job_id'],product=row['product_id'],
                 frame=row['frame_id'],model=row['model'],status='settled' if settled else 'uncertain',external=row['external_id'] or '',
                 reserved=0 if settled else reserved,charged=old['charged_rub'] if settled else 0,cost=old['cost_rub'] if settled else 0,
                 markup=markup,billable=billable,note='Перенесено незавершённое задание предыдущей версии'))
        conn.execute(sa.text('UPDATE generations SET paid_operation_id=:oid WHERE id=:id'),{'oid':oid,'id':row['id']})
