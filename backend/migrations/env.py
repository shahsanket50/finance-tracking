"""Alembic migration environment. Implements TRD §3."""
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from core.events.models import Base
from core.models.mutable import (  # noqa: F401
    Account,
    Budget,
    CategoryOverride,
    MerchantSectionMap,
    NotificationPreferences,
    Settings,
    StatementCredential,
)

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = os.environ["DATABASE_URL"]
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = os.environ["DATABASE_URL"]
    connectable = engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
