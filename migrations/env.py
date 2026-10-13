"""Alembic: миграции схемы PostgreSQL. Адрес базы берётся из .env (DATABASE_URL)."""
from alembic import context
from sqlalchemy import engine_from_config, pool

from dreamgoods.core import config as app_config
from dreamgoods.db.models import Base

cfg = context.config
cfg.set_main_option("sqlalchemy.url", app_config.DATABASE_URL.replace("%", "%%"))
target_metadata = Base.metadata


def run_offline():
    context.configure(url=app_config.DATABASE_URL, target_metadata=target_metadata, literal_binds=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    connectable = engine_from_config(cfg.get_section(cfg.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
