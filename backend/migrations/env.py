from alembic import context

from app.core.config import Settings
from app.core.database import create_db_engine
from app.core.models import Base
from app.modules.auth import models  # noqa: F401
from app.modules.chat import models as chat_models  # noqa: F401
from app.modules.feedback import models as feedback_models  # noqa: F401
from app.modules.ingestion import models as ingestion_models  # noqa: F401
from app.modules.knowledge import models as knowledge_models  # noqa: F401

config = context.config


def run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        version_table_schema=connection.dialect.default_schema_name,
        compare_type=True,
        # Reflection calls the default schema None; still exclude our explicitly scoped tracker.
        include_name=lambda name, type_, parents: (
            not (type_ == "table" and name == "alembic_version")
        ),
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        run_migrations(supplied_connection)
    else:
        engine = create_db_engine(Settings())
        try:
            with engine.connect() as connection:
                run_migrations(connection)
        finally:
            engine.dispose()
