from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  (register tables)
from app.config import settings
from app.db import Base

target_metadata = Base.metadata


def _url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or settings.db_url


def run_migrations_offline():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = context.config.attributes.get("connection")
    own = connectable is None
    if own:
        connectable = create_engine(_url()).connect()
    try:
        context.configure(connection=connectable, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        if own:
            connectable.commit()
    finally:
        if own:
            connectable.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
