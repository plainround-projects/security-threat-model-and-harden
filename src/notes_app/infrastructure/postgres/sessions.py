"""Sessions in PostgreSQL, keyed by the SHA-256 of the cookie value."""

from __future__ import annotations

from datetime import datetime

from notes_app.domain.models import Session
from notes_app.infrastructure.postgres.database import Database

_INSERT = (
    "INSERT INTO sessions (token_hash, user_id, csrf_token, created_at, last_seen_at, expires_at) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)
_SELECT = (
    "SELECT token_hash, user_id, csrf_token, created_at, last_seen_at, expires_at FROM sessions WHERE token_hash = %s"
)
_TOUCH = "UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s"
_DELETE = "DELETE FROM sessions WHERE token_hash = %s"
_PURGE = "DELETE FROM sessions WHERE expires_at <= %s"


def _timestamp(value: object) -> datetime:
    assert isinstance(value, datetime)  # noqa: S101 - timestamptz columns always come back as datetime
    return value


class PostgresSessionRepository:
    """The ``SessionRepository`` port over PostgreSQL."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, session: Session) -> None:
        """Insert a session."""
        values = (
            session.token_hash,
            session.user_id,
            session.csrf_token,
            session.created_at,
            session.last_seen_at,
            session.expires_at,
        )
        with self._database.connection() as connection:
            connection.execute(_INSERT, values)

    def get(self, token_hash: str) -> Session | None:
        """Fetch a session by token hash."""
        with self._database.connection() as connection:
            row = connection.execute(_SELECT, (token_hash,)).fetchone()
        if row is None:
            return None
        return Session(
            token_hash=str(row[0]),
            user_id=None if row[1] is None else int(str(row[1])),
            csrf_token=str(row[2]),
            created_at=_timestamp(row[3]),
            last_seen_at=_timestamp(row[4]),
            expires_at=_timestamp(row[5]),
        )

    def touch(self, token_hash: str, seen_at: datetime) -> None:
        """Record activity."""
        with self._database.connection() as connection:
            connection.execute(_TOUCH, (seen_at, token_hash))

    def delete(self, token_hash: str) -> None:
        """Remove a session."""
        with self._database.connection() as connection:
            connection.execute(_DELETE, (token_hash,))

    def purge_expired(self, now: datetime) -> int:
        """Remove sessions past their absolute expiry."""
        with self._database.connection() as connection:
            return connection.execute(_PURGE, (now,)).rowcount
