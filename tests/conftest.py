import os
from contextlib import contextmanager

import pytest
from sqlalchemy import BigInteger, create_engine, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dreamgoods import db
from dreamgoods.db.models import Base, Organization, Client, Project, Product, Frame

@compiles(BigInteger, 'sqlite')
def integer_sqlite(element, compiler, **kw):
    return 'INTEGER'

@pytest.fixture
def database(monkeypatch):
    url = os.environ.get('TEST_DATABASE_URL')
    if url:
        from alembic import command
        from alembic.config import Config
        from dreamgoods.core import config
        monkeypatch.setattr(config, 'DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        engine = create_engine(url)
        with engine.begin() as c:
            c.execute(text('TRUNCATE organizations CASCADE'))
    else:
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    @contextmanager
    def session():
        with factory() as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise
    monkeypatch.setattr(db, 'session', session)
    monkeypatch.setattr(db, 'engine', engine)
    with session() as s:
        org = Organization(name='Test', settings={'api_key':'fake-test-key'})
        s.add(org); s.flush()
        client = Client(org_id=org.id, name='Test', balance_rub=200, billing=True)
        s.add(client); s.flush()
        project = Project(client_id=client.id, name='Test')
        s.add(project); s.flush()
        product = Product(project_id=project.id, sku='SKU')
        s.add(product); s.flush()
        frame = Frame(product_id=product.id, position=1, prompt='studio product', block='studio')
        s.add(frame); s.flush()
        ids = dict(org=org.id, client=client.id, project=project.id, product=product.id, frame=frame.id)
    yield engine, ids
    engine.dispose()
