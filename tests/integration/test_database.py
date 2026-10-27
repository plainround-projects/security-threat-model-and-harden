"""The pool, the probe and the privileges of the application's database role."""

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from notes_app.infrastructure.postgres.database import Database
from notes_app.infrastructure.settings import DatabaseSettings

pytestmark = pytest.mark.integration


def test_ping_is_true_while_open_and_false_after_close(container):
    assert container.database.ping() is True
    container.database.close()
    assert container.database.ping() is False


def test_opening_the_pool_with_a_wrong_password_fails_loudly(settings):
    wrong = DatabaseSettings(
        host=settings.database.host,
        port=settings.database.port,
        name=settings.database.name,
        user=settings.database.user,
        password="definitely-not-the-password",
        connect_timeout_seconds=2,
    )
    database = Database(wrong)
    with pytest.raises(PoolTimeout):
        database.open()
    database.close()


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE intruder (id int)",
        "DROP TABLE users",
        "ALTER TABLE users ADD COLUMN is_admin boolean",
        "TRUNCATE users CASCADE",
        "CREATE ROLE another LOGIN",
    ],
)
def test_the_application_role_cannot_change_the_schema(container, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), container.database.connection() as connection:
        connection.execute(statement)


def test_the_application_role_can_do_ordinary_work(container):
    with container.database.connection() as connection:
        connection.execute("INSERT INTO users (username, password_hash) VALUES ('worker', 'h')")
        assert connection.execute("SELECT count(*) FROM users").fetchone() == (1,)
