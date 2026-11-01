"""Реальные пути обновления dev-ui и ранней Dev-GPT в изолированных схемах PostgreSQL."""
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from dreamgoods.core import config


@pytest.mark.postgres
@pytest.mark.parametrize('legacy', [False, True])
def test_upgrade_preserves_data_and_handles_legacy_0013(monkeypatch, legacy):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url: pytest.skip('TEST_DATABASE_URL required')
    base = create_engine(url)
    schema = 'migration_test_' + uuid.uuid4().hex
    with base.begin() as c: c.execute(text(f'CREATE SCHEMA {schema}'))
    scoped_url = make_url(url).update_query_dict({'options':f'-csearch_path={schema}'}).render_as_string(hide_password=False)
    monkeypatch.setattr(config, 'DATABASE_URL', scoped_url)
    engine = create_engine(scoped_url)
    cfg = Config('alembic.ini')
    try:
        command.upgrade(cfg, '0012' if legacy else '0018')
        with engine.begin() as c:
            c.execute(text("INSERT INTO organizations (id,name,settings,created_at) VALUES (1,'Preserved','{}',now())"))
            c.execute(text("INSERT INTO clients (id,org_id,name,balance_rub,billing,contact,created_at) VALUES (1,1,'Kept',123.45,true,'',now())"))
        if legacy:
            path = Path(__file__).parent/'fixtures/legacy_gpt_0013.py'
            spec = importlib.util.spec_from_file_location('legacy_migration',path)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            with engine.begin() as c:
                with Operations.context(MigrationContext.configure(c)): module.upgrade()
            command.stamp(cfg, '0013')
        command.upgrade(cfg, '0019')
        from dreamgoods.db.models import Project, Product, Frame, Generation
        with engine.begin() as c:
            pid=c.execute(Project.__table__.insert().values(client_id=1,name='Pending project').returning(Project.id)).scalar_one()
            prod=c.execute(Product.__table__.insert().values(project_id=pid,sku='PENDING').returning(Product.id)).scalar_one()
            fid=c.execute(Frame.__table__.insert().values(product_id=prod,position=1,prompt='test').returning(Frame.id)).scalar_one()
            gid=c.execute(Generation.__table__.insert().values(frame_id=fid,status='pending',external_id='legacy-task',model='test').returning(Generation.id)).scalar_one()
        command.upgrade(cfg, 'head')
        with engine.connect() as c:
            assert c.scalar(text('SELECT count(*) FROM paid_operations'))==1
            assert c.scalar(text('SELECT status FROM paid_operations'))=='uncertain'
            assert c.scalar(text('SELECT paid_operation_id FROM generations WHERE id=:id'),{'id':gid})==f'legacy-{gid}'
            assert float(c.scalar(text('SELECT balance_rub FROM clients WHERE id=1'))) == pytest.approx(123.45)
            assert c.scalar(text('SELECT version_num FROM alembic_version')) == '0020'
            assert inspect(c).has_table('topup_requests')
            assert 'months' in {x['name'] for x in inspect(c).get_columns('topup_requests')}
            assert inspect(c).get_columns('clients')[0] is not None
        if not legacy:
            command.downgrade(cfg, '0012')
            command.upgrade(cfg, 'head')
    finally:
        engine.dispose()
        with base.begin() as c: c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        base.dispose()
