"""Users in PostgreSQL."""

from __future__ import annotations

from psycopg.errors import UniqueViolation

from notes_app.domain.errors import UsernameTakenError
from notes_app.domain.models import User
from notes_app.infrastructure.postgres.database import Database

_INSERT = "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id"
_BY_USERNAME = "SELECT id, username, password_hash FROM users WHERE username = %s"
_BY_ID = "SELECT id, username, password_hash FROM users WHERE id = %s"
_UPDATE_HASH = "UPDATE users SET password_hash = %s WHERE id = %s"


class PostgresUserRepository:
    """The ``UserRepository`` port over PostgreSQL."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, username: str, password_hash: str) -> User:
        """Insert a user; the unique constraint, not a prior lookup, decides a duplicate (no race)."""
        try:
            with self._database.connection() as connection:
                row = connection.execute(_INSERT, (username, password_hash)).fetchone()
        except UniqueViolation:
            raise UsernameTakenError(username) from None
        assert row is not None  # noqa: S101 - RETURNING always yields the inserted row
        return User(id=int(str(row[0])), username=username, password_hash=password_hash)

    def by_username(self, username: str) -> User | None:
        """Find a user by canonical username."""
        with self._database.connection() as connection:
            row = connection.execute(_BY_USERNAME, (username,)).fetchone()
        return None if row is None else User(id=int(str(row[0])), username=str(row[1]), password_hash=str(row[2]))

    def by_id(self, user_id: int) -> User | None:
        """Find a user by id."""
        with self._database.connection() as connection:
            row = connection.execute(_BY_ID, (user_id,)).fetchone()
        return None if row is None else User(id=int(str(row[0])), username=str(row[1]), password_hash=str(row[2]))

    def update_password_hash(self, user_id: int, password_hash: str) -> None:
        """Replace the stored hash."""
        with self._database.connection() as connection:
            connection.execute(_UPDATE_HASH, (password_hash, user_id))
