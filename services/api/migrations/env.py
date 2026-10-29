import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    # app_runtime can only see/read its own "app" schema; scanning every
    # schema in the database (e.g. n8n's) would fail with a permission
    # error, so autogenerate is scoped to just this one.
    if type_ == "schema":
        return name in (None, target_metadata.schema)
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=target_metadata.schema,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    # version_table_schema keeps alembic_version inside "app" too --
    # app_runtime has no privileges on "public" to create it there.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=target_metadata.schema,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
