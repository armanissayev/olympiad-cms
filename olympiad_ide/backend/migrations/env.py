from alembic import context
from sqlalchemy import create_engine, pool

from app.database import Base, database_url
from app import models  # noqa: F401
from app import telemetry_models  # noqa: F401
from app import execution_models  # noqa: F401
from app import cms_identity_models  # noqa: F401

config = context.config
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
