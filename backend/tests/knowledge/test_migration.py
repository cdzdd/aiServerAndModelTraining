from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


def test_upgrade_preserves_existing_users_and_downgrade_only_removes_knowledge(database_url):
    schema = f"migration_{uuid4().hex}"
    admin_engine = create_engine(database_url.get_secret_value(), hide_parameters=True)
    with admin_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped_url = make_url(database_url.get_secret_value()).update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    )
    engine = create_engine(scoped_url, hide_parameters=True)
    config = Config("alembic.ini")
    user_id = uuid4()
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "002_auth")
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,username,display_name,password_hash,role,is_active) "
                    "VALUES (:id,'migration-user','existing','test-only','user',true)"
                ),
                {"id": user_id},
            )
            command.upgrade(config, "head")
            assert {"knowledge_bases", "knowledge_memberships", "faqs"} <= set(
                inspect(connection).get_table_names()
            )
            assert connection.scalar(text("SELECT id FROM users")) == user_id
            command.check(config)
            command.downgrade(config, "002_auth")
            assert "knowledge_bases" not in inspect(connection).get_table_names()
            assert connection.scalar(text("SELECT id FROM users")) == user_id
            command.upgrade(config, "head")
            command.check(config)
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()
