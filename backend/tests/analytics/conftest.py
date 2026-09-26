import pytest

from tests import conftest as database_fixtures
from tests.auth import conftest as auth_fixtures

auth_app = auth_fixtures.auth_app
client = auth_fixtures.client
user = auth_fixtures.user
signed_in = auth_fixtures.signed_in
admin = auth_fixtures.admin


@pytest.fixture
def migrated_engine(database_url):
    # Historical fixtures cannot accumulate or be recovered by the next test app.
    yield from database_fixtures.migrated_engine.__wrapped__(database_url)
