"""The sign-in throttle, kept in PostgreSQL so every worker process (and every replica) sees the same count."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from notes_app.domain.errors import LoginThrottledError
from notes_app.domain.throttle import retry_after_seconds
from notes_app.infrastructure.postgres.database import Database

_FAILURES = "SELECT attempted_at FROM login_failures WHERE key_hash = %s AND attempted_at > %s"
_INSERT = "INSERT INTO login_failures (key_hash, attempted_at) VALUES (%s, %s)"
_PRUNE = "DELETE FROM login_failures WHERE attempted_at <= %s"
_RESET = "DELETE FROM login_failures WHERE key_hash = %s"


def _key_hash(key: str) -> str:
    """Store a digest of ``client address|username``, so the table holds no usernames or addresses."""
    return hashlib.sha256(key.encode()).hexdigest()


class PostgresLoginThrottle:
    """Allows ``max_failures`` failed sign-ins per client address and username in a window."""

    def __init__(self, database: Database, *, max_failures: int, window_seconds: int) -> None:
        self._database = database
        self._max_failures = max_failures
        self._window = timedelta(seconds=window_seconds)

    def check(self, key: str, now: datetime) -> None:
        """Raise ``LoginThrottledError`` when the key already used all its failures in the window."""
        with self._database.connection() as connection:
            rows = connection.execute(_FAILURES, (_key_hash(key), now - self._window)).fetchall()
        wait = retry_after_seconds(
            (row[0] for row in rows if isinstance(row[0], datetime)),
            now=now,
            max_failures=self._max_failures,
            window=self._window,
        )
        if wait is not None:
            raise LoginThrottledError(wait)

    def record_failure(self, key: str, now: datetime) -> None:
        """Count one failure and drop rows that left every window."""
        with self._database.connection() as connection:
            connection.execute(_INSERT, (_key_hash(key), now))
            connection.execute(_PRUNE, (now - self._window,))

    def reset(self, key: str) -> None:
        """Forget the key's failures after a successful sign-in."""
        with self._database.connection() as connection:
            connection.execute(_RESET, (_key_hash(key),))
