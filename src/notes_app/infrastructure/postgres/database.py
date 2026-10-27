"""Connection pool and health probe."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

from notes_app.infrastructure.settings import DatabaseSettings


class Database:
    """A pool of connections to the application's limited role. ``connection()`` commits on success and rolls
    back on an exception."""

    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
        self._pool: ConnectionPool[psycopg.Connection[tuple[object, ...]]] = ConnectionPool(
            settings.conninfo(), min_size=settings.pool_min, max_size=settings.pool_max, open=False, timeout=10
        )

    def open(self) -> None:
        """Open the pool and wait for the minimum number of connections; raises when the database is down."""
        self._pool.open(wait=True, timeout=self._settings.connect_timeout_seconds + 5)

    def close(self) -> None:
        """Close every connection (graceful shutdown)."""
        self._pool.close()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        """A pooled connection in a transaction."""
        with self._pool.connection(timeout=10) as connection:
            yield connection

    def ping(self) -> bool:
        """True when a trivial query succeeds."""
        try:
            with self.connection() as connection:
                connection.execute("SELECT 1")
        except (psycopg.Error, Exception):
            return False
        return True
