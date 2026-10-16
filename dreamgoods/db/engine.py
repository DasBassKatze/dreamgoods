"""Подключение к PostgreSQL и сессии."""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core import config

# Сотни потоков заданий держат соединение лишь на короткие записи; при пике ждут свободное (pool_timeout),
# а не открывают новые сверх лимита PostgreSQL (max_connections = 100 по умолчанию).
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=40, pool_timeout=120,
                       future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session():
    """with session() as s: … — коммит при успехе, откат при ошибке."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
