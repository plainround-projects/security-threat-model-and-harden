# psycopg 3 and psycopg_pool

## What it is

psycopg is the **database driver** for PostgreSQL in Python: the library that opens a network connection to the server, sends SQL, and turns the rows that come back into Python values. `psycopg_pool` is a companion package that keeps a set of open connections ready (a **connection pool**), because opening a connection is slow (a network handshake, a login, a new server process) and a web app serves many requests. Pinned versions: `psycopg==3.3.6`, `psycopg-pool==3.3.3`, with `psycopg-binary==3.3.6` (a prebuilt copy of the C library `libpq`, so no compiler is needed; the extra is `psycopg[binary,pool]` in `pyproject.toml`).

## Why this repository uses it

Two security properties come from the driver. First, **parameter binding**: values are sent to the server separately from the SQL text, which is what stops SQL injection (`tech/sql.md`). Second, **transaction handling**: the repository's `Database.connection()` helper commits on success and rolls back on any exception, so a failure never leaves half a change.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/notes_app/infrastructure/postgres/database.py` | The `Database` class: pool, `open`, `close`, `connection()`, `ping`. |
| `src/notes_app/infrastructure/postgres/{users,notes,sessions,throttle,audit}.py` | Repositories that run parameterized statements. |
| `src/notes_app/infrastructure/settings.py` | `DatabaseSettings.conninfo()` builds the connection string. |
| `tests/conftest.py` | A second, direct connection as the owner role for test set-up and checks. |

## How it works underneath

1. `psycopg.connect(...)` opens a TCP connection to the server, authenticates, and returns a `Connection`.
2. `connection.execute(sql, params)` creates a **cursor**, sends the statement plus parameters, and returns the cursor. `.fetchone()` and `.fetchall()` read rows as tuples; `.rowcount` says how many rows a write touched.
3. By default psycopg 3 sends the parameters to the server as separate values (**server-side binding**). The server never sees them as SQL.
4. Nothing is final until the transaction is **committed**. By default the first statement opens a transaction. Leaving a `with connection:` block normally commits; leaving it through an exception rolls back.
5. A **pool** holds a minimum number of open connections and grows to a maximum. `pool.connection()` lends one, waits (up to a timeout) if all are busy, and takes it back at the end of the `with` block.

### Ideas you need first

- **A database driver.** A library that speaks the database's network protocol so your program does not have to: it opens a connection, sends statements, reads rows.
- **A cursor and a row.** Running a statement gives you a cursor, a handle for reading results; each result is a row, returned as a tuple of values in column order.
- **A transaction.** Statements grouped so they all take effect or none do. The `with` block in `Database.connection()` commits at the end, or rolls back if an exception left it.
- **A connection pool.** Opening a database connection is slow. A pool keeps some open and lends them out, taking each back when the `with` block ends.
- **A context manager.** `with thing as name:` runs set-up, then your block, then clean-up even after an error.

## Walkthrough of this repository's use

### Connection string

```python
def conninfo(self) -> str:
    """A libpq connection string. Contains the password; never log it."""
    return (
        f"host={self.host} port={self.port} dbname={self.name} user={self.user} "
        f"password={self.password} connect_timeout={self.connect_timeout_seconds}"
    )
```
`libpq` is PostgreSQL's own client library; this is its key=value format. `connect_timeout=5` stops a dead database from freezing start-up. The dataclass field is declared `password: str = field(repr=False)` so printing the settings object does not show the password.

### The pool

```python
self._pool: ConnectionPool[psycopg.Connection[tuple[object, ...]]] = ConnectionPool(
    settings.conninfo(), min_size=settings.pool_min, max_size=settings.pool_max, open=False, timeout=10
)
```
`min_size` 1 and `max_size` 8 by default (`NOTES_DB_POOL_MIN`, `NOTES_DB_POOL_MAX`). `open=False` does not connect yet, because the module should be importable without a database. `timeout=10` is how long a request waits for a free connection before raising. The long type after the colon is only for `mypy`: a pool of connections whose rows are tuples of objects.

```python
def open(self) -> None:
    self._pool.open(wait=True, timeout=self._settings.connect_timeout_seconds + 5)
```
`wait=True` blocks until the minimum connections are really open. If the database is down or the password is wrong this raises, `build_app()` fails, and the worker refuses to start instead of serving errors. (The integration test `test_opening_the_pool_with_a_wrong_password_fails_loudly` proves it.)

```python
@contextmanager
def connection(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with self._pool.connection(timeout=10) as connection:
        yield connection
```
One short helper that every repository uses: `with self._database.connection() as connection:`. On a normal exit the pool commits; on an exception it rolls back; either way the connection returns to the pool.

```python
def close(self) -> None:
    self._pool.close()
```
Called from gunicorn's `worker_exit` hook (`tech/gunicorn.md`).

### Placeholders and results

```python
row = connection.execute(SELECT_NOTE, (note_id,)).fetchone()
return None if row is None else to_note(row)
```
`%s` in the statement, a tuple of values (note the comma in `(note_id,)`: a one-item tuple). `fetchone()` returns a tuple or `None`. `to_note` maps columns to the `Note` dataclass using `int(str(row[0]))` for the id columns and `str(...)` for the text columns, because the row type is `tuple[object, ...]` and `mypy --strict` insists on checked conversions.

```python
rows = connection.execute(LIST_VISIBLE, {"user_id": user_id}).fetchall()
```
Named placeholders with a dictionary.

### JSON column

```python
from psycopg.types.json import Jsonb
connection.execute(_INSERT, (event.action.value, event.outcome, event.user_id, event.ip, Jsonb(detail)))
```
`Jsonb(dict)` tells psycopg to send a Python dictionary as PostgreSQL `jsonb`.

### Errors

```python
from psycopg.errors import UniqueViolation
try:
    with self._database.connection() as connection:
        row = connection.execute(_INSERT, (username, password_hash)).fetchone()
except UniqueViolation:
    raise UsernameTakenError(username) from None
```
PostgreSQL error codes become Python exception classes. The unique constraint on `users.username` is what decides "taken"; the code does not look first. `PostgresAuditLog.record` catches `psycopg.Error` so an audit-table failure is logged loudly but does not fail the user's request (the structured log line written first is the fallback record).

### Every statement the application runs

All statements are constants with `%s` (or `%(name)s`) placeholders; values go in a separate tuple or dictionary.

**`users.py`.** `INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id`; `SELECT id, username, password_hash FROM users WHERE username = %s`; the same `WHERE id = %s`; `UPDATE users SET password_hash = %s WHERE id = %s`. `add` catches `UniqueViolation`, the exception psycopg raises when the unique constraint refuses a row.

**`notes.py`.** `INSERT INTO notes (owner_id, title, content) VALUES (%s, %s, %s) RETURNING id, owner_id, title, content, created_at, updated_at`; `SELECT ... FROM notes WHERE id = %s`; `UPDATE notes SET title = %s, content = %s, updated_at = now() WHERE id = %s RETURNING ...`; `DELETE FROM notes WHERE id = %s` (its shares disappear through `ON DELETE CASCADE`); `SELECT user_id FROM note_shares WHERE note_id = %s`; `INSERT INTO note_shares (note_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING` (sharing twice is a no-op); and `LIST_VISIBLE`, the join-and-`EXISTS` query with the named placeholder `%(user_id)s` used three times, passed as `{"user_id": user_id}`. `list_visible` turns each row into a `VisibleNote` with `NoteRole(str(row[7]))`.

**`sessions.py`.** `INSERT INTO sessions (token_hash, user_id, csrf_token, created_at, last_seen_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s)`; `SELECT ... WHERE token_hash = %s`; `UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s`; `DELETE ... WHERE token_hash = %s`; `DELETE FROM sessions WHERE expires_at <= %s` (the number of rows removed is `cursor.rowcount`).

**`throttle.py`.** `SELECT attempted_at FROM login_failures WHERE key_hash = %s AND attempted_at > %s`; `INSERT INTO login_failures (key_hash, attempted_at) VALUES (%s, %s)`; `DELETE FROM login_failures WHERE attempted_at <= %s` (prune what left the window); `DELETE FROM login_failures WHERE key_hash = %s` (reset after a good sign-in). The check passes the times to the pure function `retry_after_seconds`.

**`audit.py`.** `INSERT INTO audit_events (action, outcome, user_id, ip, detail) VALUES (%s, %s, %s, %s, %s)` where `detail` is wrapped as `Jsonb(detail)` so the dictionary is stored as `jsonb`.

Every method opens `with self._database.connection() as connection:`, so each is its own transaction: it commits when the block ends normally and rolls back if an exception leaves it.

### Line by line: `src/notes_app/infrastructure/postgres/database.py`

```python
"""Connection pool and health probe."""
```

The docstring: the connection pool and the health probe. A **pool** keeps a few database connections open and lends them out, because opening one per request is slow.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
from collections.abc import Iterator
from contextlib import contextmanager
```

`Iterator` is a type name; `contextmanager` turns a function with one `yield` into something usable in a `with` block.

```python
import psycopg
from psycopg_pool import ConnectionPool
```

`psycopg` is the PostgreSQL driver; `ConnectionPool` comes from the separate `psycopg_pool` package.

```python
from notes_app.infrastructure.settings import DatabaseSettings
```

The `DatabaseSettings` record (host, port, password and so on).

```python
class Database:
    """A pool of connections to the application's limited role. ``connection()`` commits on success and rolls
    back on an exception."""
```

`Database` is a pool of connections to the application's limited role. `connection()` commits when the block ends normally and rolls back on an exception. A **transaction** is a group of statements that all succeed or all fail together.

```python
    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
        self._pool: ConnectionPool[psycopg.Connection[tuple[object, ...]]] = ConnectionPool(
            settings.conninfo(), min_size=settings.pool_min, max_size=settings.pool_max, open=False, timeout=10
        )
```

The pool is created with the connection string, a minimum and a maximum size from the settings, `open=False` (do not connect inside the constructor) and a 10-second wait for a free connection.

```python
    def open(self) -> None:
        """Open the pool and wait for the minimum number of connections; raises when the database is down."""
        self._pool.open(wait=True, timeout=self._settings.connect_timeout_seconds + 5)
```

`open` opens the pool and waits for the minimum number of connections, for the connect timeout plus 5 seconds. It raises if the database is down, so start-up fails fast.

```python
    def close(self) -> None:
        """Close every connection (graceful shutdown)."""
        self._pool.close()
```

`close` closes every connection, for a clean shutdown.

```python
    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        """A pooled connection in a transaction."""
        with self._pool.connection(timeout=10) as connection:
            yield connection
```

`connection` is a context manager: `with database.connection() as c:` borrows a connection and returns it afterwards, inside a transaction.

```python
    def ping(self) -> bool:
        """True when a trivial query succeeds."""
        try:
            with self.connection() as connection:
                connection.execute("SELECT 1")
        except (psycopg.Error, Exception):
            return False
        return True
```

`ping` runs `SELECT 1`, the cheapest query. Any error gives `False`, otherwise `True`. A probe must report failure, never raise.

### Line by line: `src/notes_app/infrastructure/postgres/audit.py`

```python
"""The audit trail: a structured log line first, then an append-only row."""
```

The docstring: the audit trail is a structured log line first, then an append-only table row.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import logging

import psycopg
from psycopg.types.json import Jsonb
```

`logging` writes log lines. `psycopg` is imported to catch its errors, and `Jsonb` wraps a Python dictionary so PostgreSQL stores it in a `jsonb` column.

```python
from notes_app.domain.models import AuditEvent
from notes_app.infrastructure.postgres.database import Database
```

The event type and the `Database` wrapper.

```python
_INSERT = "INSERT INTO audit_events (action, outcome, user_id, ip, detail) VALUES (%s, %s, %s, %s, %s)"
_log = logging.getLogger("notes_app.audit")
```

`_INSERT` has five `%s` placeholders: psycopg sends the statement and the values separately, so a value can never be read as SQL. `_log` is the logger named `notes_app.audit`.

```python
class PostgresAuditLog:
    """Writes each event to the ``audit`` logger and to the ``audit_events`` table.

    The application's database role can insert and read that table but not update or delete it, so a normal user
    of the app (or a bug) cannot rewrite history. A database failure is logged loudly and does not fail the
    request: the log line above is the fallback record.
    """
```

`PostgresAuditLog` writes each event to the log and to the `audit_events` table. The docstring explains the design: the database role can insert and read that table but not update or delete it, so a user or a bug cannot rewrite history; and a database failure is logged loudly but does not fail the request, because the log line is the fallback record.

```python
    def __init__(self, database: Database) -> None:
        self._database = database
```

The constructor stores the database wrapper.

```python
    def record(self, event: AuditEvent) -> None:
        """Write one event."""
        detail = dict(event.detail)
        _log.info(
            "audit",
            extra={
                "action": event.action.value,
                "outcome": event.outcome,
                "user_id": event.user_id,
                "ip": event.ip,
                **detail,
            },
        )
```

`record` first turns the event's detail pairs into a dictionary and writes a log line `audit` with the action, outcome, user id, IP and the detail fields. The log line comes first so a record exists even if the database write fails.

```python
        try:
            with self._database.connection() as connection:
                connection.execute(_INSERT, (event.action.value, event.outcome, event.user_id, event.ip, Jsonb(detail)))
```

It then borrows a connection and inserts the row, with the detail as `Jsonb`.

```python
        except psycopg.Error:
            _log.exception("audit row could not be written", extra={"action": event.action.value})
```

A `psycopg.Error` is logged with its stack trace and swallowed.

### Line by line: `src/notes_app/infrastructure/postgres/users.py`

```python
"""Users in PostgreSQL."""
```

The docstring: users in PostgreSQL.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
from psycopg.errors import UniqueViolation

from notes_app.domain.errors import UsernameTakenError
from notes_app.domain.models import User
from notes_app.infrastructure.postgres.database import Database
```

`UniqueViolation` is the error PostgreSQL raises when a unique rule is broken. The other imports are the domain error, the model and the database wrapper.

```python
_INSERT = "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id"
_BY_USERNAME = "SELECT id, username, password_hash FROM users WHERE username = %s"
_BY_ID = "SELECT id, username, password_hash FROM users WHERE id = %s"
_UPDATE_HASH = "UPDATE users SET password_hash = %s WHERE id = %s"
```

Four statements with placeholders: insert a user and return the new id, find by username, find by id, replace the password hash.

```python
class PostgresUserRepository:
    """The ``UserRepository`` port over PostgreSQL."""

    def __init__(self, database: Database) -> None:
        self._database = database
```

`PostgresUserRepository` implements the `UserRepository` port.

```python
    def add(self, username: str, password_hash: str) -> User:
        """Insert a user; the unique constraint, not a prior lookup, decides a duplicate (no race)."""
        try:
            with self._database.connection() as connection:
                row = connection.execute(_INSERT, (username, password_hash)).fetchone()
        except UniqueViolation:
            raise UsernameTakenError(username) from None
        assert row is not None  # noqa: S101 - RETURNING always yields the inserted row
        return User(id=int(str(row[0])), username=username, password_hash=password_hash)
```

`add` tries the insert. If the database reports a unique violation, a `UsernameTakenError` is raised (`from None` hides the technical error). The docstring explains why: the unique constraint decides a duplicate, not an earlier "does it exist?" lookup, because two sign-ups at the same moment would both pass such a lookup (a race). The `assert` tells the type checker `RETURNING` always gives a row.

```python
    def by_username(self, username: str) -> User | None:
        """Find a user by canonical username."""
        with self._database.connection() as connection:
            row = connection.execute(_BY_USERNAME, (username,)).fetchone()
        return None if row is None else User(id=int(str(row[0])), username=str(row[1]), password_hash=str(row[2]))
```

`by_username` fetches one row and builds a `User`, or returns `None`. `int(str(row[0]))` converts the column value to a number in a form the type checker accepts.

```python
    def by_id(self, user_id: int) -> User | None:
        """Find a user by id."""
        with self._database.connection() as connection:
            row = connection.execute(_BY_ID, (user_id,)).fetchone()
        return None if row is None else User(id=int(str(row[0])), username=str(row[1]), password_hash=str(row[2]))
```

`by_id` does the same by id.

```python
    def update_password_hash(self, user_id: int, password_hash: str) -> None:
        """Replace the stored hash."""
        with self._database.connection() as connection:
            connection.execute(_UPDATE_HASH, (password_hash, user_id))
```

`update_password_hash` replaces the hash.

### Line by line: `src/notes_app/infrastructure/postgres/sessions.py`

```python
"""Sessions in PostgreSQL, keyed by the SHA-256 of the cookie value."""
```

The docstring: sessions in PostgreSQL, keyed by the SHA-256 of the cookie value.

```python
from __future__ import annotations

from datetime import datetime

from notes_app.domain.models import Session
from notes_app.infrastructure.postgres.database import Database
```

Imports: `datetime`, the `Session` model and the `Database` wrapper.

```python
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
```

The five statements: insert a session, select one by token hash, update `last_seen_at`, delete one, and delete every session whose expiry is at or before a given time. Long text is split over lines inside parentheses; Python joins adjacent string pieces.

```python
def _timestamp(value: object) -> datetime:
    assert isinstance(value, datetime)  # noqa: S101 - timestamptz columns always come back as datetime
    return value
```

`_timestamp` checks that a value is a `datetime` (columns of type `timestamptz` always come back as one) so the type checker is satisfied.

```python
class PostgresSessionRepository:
    """The ``SessionRepository`` port over PostgreSQL."""

    def __init__(self, database: Database) -> None:
        self._database = database
```

`PostgresSessionRepository` implements the `SessionRepository` port.

```python
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
```

`add` builds the six values in column order and inserts them.

```python
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
```

`get` selects by hash. No row gives `None`; otherwise a `Session` is built with the user id converted to a number unless it is `None` (an anonymous session).

```python
    def touch(self, token_hash: str, seen_at: datetime) -> None:
        """Record activity."""
        with self._database.connection() as connection:
            connection.execute(_TOUCH, (seen_at, token_hash))
```

`touch` records activity.

```python
    def delete(self, token_hash: str) -> None:
        """Remove a session."""
        with self._database.connection() as connection:
            connection.execute(_DELETE, (token_hash,))
```

`delete` removes one session.

```python
    def purge_expired(self, now: datetime) -> int:
        """Remove sessions past their absolute expiry."""
        with self._database.connection() as connection:
            return connection.execute(_PURGE, (now,)).rowcount
```

`purge_expired` deletes expired sessions and returns `rowcount`, the number of rows deleted.

### Line by line: `src/notes_app/infrastructure/postgres/throttle.py`

```python
"""The sign-in throttle, kept in PostgreSQL so every worker process (and every replica) sees the same count."""
```

The docstring: the throttle is kept in PostgreSQL so that every worker process, and every replica, sees the same count. A throttle in a Python dictionary would be separate in each worker and an attacker would get a multiple of the limit.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import hashlib
from datetime import datetime, timedelta

from notes_app.domain.errors import LoginThrottledError
from notes_app.domain.throttle import retry_after_seconds
from notes_app.infrastructure.postgres.database import Database
```

Imports: `hashlib`, time types, the throttled error, the pure window rule and the database wrapper.

```python
_FAILURES = "SELECT attempted_at FROM login_failures WHERE key_hash = %s AND attempted_at > %s"
_INSERT = "INSERT INTO login_failures (key_hash, attempted_at) VALUES (%s, %s)"
_PRUNE = "DELETE FROM login_failures WHERE attempted_at <= %s"
_RESET = "DELETE FROM login_failures WHERE key_hash = %s"
```

Four statements: select the failure times for a key since a given time, insert a failure, delete failures older than a time, delete all failures of a key.

```python
def _key_hash(key: str) -> str:
    """Store a digest of ``client address|username``, so the table holds no usernames or addresses."""
    return hashlib.sha256(key.encode()).hexdigest()
```

`_key_hash` stores the SHA-256 of `client address|username`, so the table holds no usernames and no addresses.

```python
class PostgresLoginThrottle:
    """Allows ``max_failures`` failed sign-ins per client address and username in a window."""
```

`PostgresLoginThrottle` allows `max_failures` failures per key in a window.

```python
    def __init__(self, database: Database, *, max_failures: int, window_seconds: int) -> None:
        self._database = database
        self._max_failures = max_failures
        self._window = timedelta(seconds=window_seconds)
```

The constructor stores the database, the limit and the window as a `timedelta`.

```python
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
```

`check` reads the key's failure times from within the window and passes them to the pure rule `retry_after_seconds`.

```python
        if wait is not None:
            raise LoginThrottledError(wait)
```

If the rule returns a wait, `LoginThrottledError` is raised with it.

```python
    def record_failure(self, key: str, now: datetime) -> None:
        """Count one failure and drop rows that left every window."""
        with self._database.connection() as connection:
            connection.execute(_INSERT, (_key_hash(key), now))
            connection.execute(_PRUNE, (now - self._window,))
```

`record_failure` inserts the failure and, in the same transaction, deletes rows older than the window so the table does not grow without limit.

```python
    def reset(self, key: str) -> None:
        """Forget the key's failures after a successful sign-in."""
        with self._database.connection() as connection:
            connection.execute(_RESET, (_key_hash(key),))
```

`reset` forgets the key's failures after a successful sign-in.

### Line by line: `src/notes_app/infrastructure/postgres/notes.py`

```python
"""Notes and shares in PostgreSQL."""
```

The docstring: notes and shares in PostgreSQL.

```python
from __future__ import annotations

from datetime import datetime

from notes_app.domain.models import Note, NoteRole, VisibleNote
from notes_app.infrastructure.postgres.database import Database
```

Imports: `datetime`, the models and the database wrapper.

```python
INSERT_NOTE = (
    "INSERT INTO notes (owner_id, title, content) VALUES (%s, %s, %s) "
    "RETURNING id, owner_id, title, content, created_at, updated_at"
)
```

`INSERT_NOTE` inserts a note with three placeholders and `RETURNING` the whole new row.

```python
SELECT_NOTE = "SELECT id, owner_id, title, content, created_at, updated_at FROM notes WHERE id = %s"
```

`SELECT_NOTE` fetches a note by id.

```python
UPDATE_NOTE = (
    "UPDATE notes SET title = %s, content = %s, updated_at = now() WHERE id = %s "
    "RETURNING id, owner_id, title, content, created_at, updated_at"
)
```

`UPDATE_NOTE` sets title and content and `updated_at = now()` for one id and returns the row.

```python
DELETE_NOTE = "DELETE FROM notes WHERE id = %s"
SELECT_SHARES = "SELECT user_id FROM note_shares WHERE note_id = %s"
INSERT_SHARE = "INSERT INTO note_shares (note_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING"
```

`DELETE_NOTE` deletes by id; `SELECT_SHARES` lists the user ids a note is shared with; `INSERT_SHARE` adds a share, and `ON CONFLICT DO NOTHING` makes sharing twice harmless.

```python
LIST_VISIBLE = """
SELECT n.id, n.owner_id, n.title, n.content, n.created_at, n.updated_at, u.username,
       CASE WHEN n.owner_id = %(user_id)s THEN 'owner' ELSE 'reader' END AS role
FROM notes n
JOIN users u ON u.id = n.owner_id
WHERE n.owner_id = %(user_id)s
   OR EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id AND s.user_id = %(user_id)s)
ORDER BY n.updated_at DESC, n.id DESC
"""
```

`LIST_VISIBLE` uses named placeholders (`%(user_id)s`, filled from a dictionary). It selects the note columns and the owner's username from `notes n` joined with `users u`; a `CASE` expression gives `'owner'` when the note is the user's and `'reader'` otherwise; the `WHERE` keeps notes the user owns, or notes for which an `EXISTS` subquery finds a share row for the user; the order is newest update first, ties by id.

```python
def to_note(row: tuple[object, ...]) -> Note:
    """Map the first six columns of a notes row."""
    return Note(
        id=int(str(row[0])),
        owner_id=int(str(row[1])),
        title=str(row[2]),
        content=str(row[3]),
        created_at=_timestamp(row[4]),
        updated_at=_timestamp(row[5]),
    )
```

`to_note` maps the first six columns of a row into a `Note`.

```python
def _timestamp(value: object) -> datetime:
    assert isinstance(value, datetime)  # noqa: S101 - timestamptz columns always come back as datetime
    return value
```

`_timestamp` checks a value is a `datetime`.

```python
class PostgresNoteRepository:
    """The ``NoteRepository`` port over PostgreSQL. All values are bound parameters."""

    def __init__(self, database: Database) -> None:
        self._database = database
```

`PostgresNoteRepository` implements the `NoteRepository` port.

```python
    def add(self, owner_id: int, title: str, content: str) -> Note:
        """Insert a note with a parameterized statement."""
        with self._database.connection() as connection:
            row = connection.execute(INSERT_NOTE, (owner_id, title, content)).fetchone()
        assert row is not None  # noqa: S101 - RETURNING always yields the inserted row
        return to_note(row)
```

`add` runs the insert with the three values and fetches the single returned row.

```python
    def get(self, note_id: int) -> Note | None:
        """Fetch one note by id."""
        with self._database.connection() as connection:
            row = connection.execute(SELECT_NOTE, (note_id,)).fetchone()
        return None if row is None else to_note(row)
```

`get` returns `None` or the note.

```python
    def shared_with(self, note_id: int) -> frozenset[int]:
        """The ids of the users a note is shared with."""
        with self._database.connection() as connection:
            rows = connection.execute(SELECT_SHARES, (note_id,)).fetchall()
        return frozenset(int(str(row[0])) for row in rows)
```

`shared_with` returns a frozen set of user ids.

```python
    def update(self, note_id: int, title: str, content: str) -> Note:
        """Replace a note's title and content."""
        with self._database.connection() as connection:
            row = connection.execute(UPDATE_NOTE, (title, content, note_id)).fetchone()
        assert row is not None  # noqa: S101 - the service checked the note exists
        return to_note(row)
```

`update` runs the update and returns the row; the service has already checked the note exists.

```python
    def delete(self, note_id: int) -> None:
        """Delete a note; its shares go with it (ON DELETE CASCADE)."""
        with self._database.connection() as connection:
            connection.execute(DELETE_NOTE, (note_id,))
```

`delete` removes the note; its shares go with it because the foreign key is `ON DELETE CASCADE`.

```python
    def share(self, note_id: int, user_id: int) -> None:
        """Share a note with a user; sharing twice is a no-op."""
        with self._database.connection() as connection:
            connection.execute(INSERT_SHARE, (note_id, user_id))
```

`share` inserts the share row.

```python
    def list_visible(self, user_id: int) -> list[VisibleNote]:
        """Notes the user owns or has been given, newest first."""
        with self._database.connection() as connection:
            rows = connection.execute(LIST_VISIBLE, {"user_id": user_id}).fetchall()
        return [VisibleNote(note=to_note(row), role=NoteRole(str(row[7])), owner_username=str(row[6])) for row in rows]
```

`list_visible` runs the join with a dictionary of parameters and builds a `VisibleNote` per row from the note columns, the role (column 7) and the owner's name (column 6).

## Try it yourself

1. See the versions:
   ```bash
   .venv/bin/python -c "import psycopg, psycopg_pool; print(psycopg.__version__, psycopg_pool.__version__, psycopg.pq.__impl__)"
   ```
   Expect `3.3.6 3.3.3 binary`.
2. With `make up` done, ask a question through a pool:
   ```bash
   set -a; . ./.env; set +a
   .venv/bin/python - <<'EOF'
   import os
   from notes_app.infrastructure.settings import Settings
   from notes_app.infrastructure.postgres.database import Database
   db = Database(Settings.from_environment(os.environ).database)
   db.open()
   with db.connection() as c:
       print(c.execute("SELECT current_user, version()").fetchone())
   print(db.ping()); db.close(); print(db.ping())
   EOF
   ```
   Expect a row starting with `('notes_app', 'PostgreSQL 18...')`, then `True`, then `False`.
3. Run the repository tests (needs `make up`):
   ```bash
   make test-integration
   ```
   Expect 20 passed.

## Mistakes people make

- Formatting values into SQL with f-strings (see `tech/sql.md`).
- Opening a new connection per request. The pool exists to avoid that.
- Forgetting to return connections (always use `with`).
- Logging the connection string. It contains the password; only `conninfo()` builds it and nothing logs it.
- Assuming a failed statement leaves earlier ones in place. A transaction rolls back as a whole.
- Using one connection from several threads at once. A pooled connection is lent to one caller at a time.

## Check yourself

1. Why is a pool used?
   *Opening a connection is slow; a pool reuses open ones across requests.*
2. What does leaving the `with` block through an exception do?
   *Rolls back the transaction and returns the connection to the pool.*
3. Why is `open=False` passed to `ConnectionPool`?
   *So importing or constructing the object does not need the database; `open()` connects explicitly and raises if it cannot.*
4. How does the code detect a duplicate username?
   *It inserts and catches `UniqueViolation`.*
5. What does `psycopg-binary` provide?
   *A precompiled libpq, so installation needs no C compiler.*

## Further reading

- psycopg 3 documentation (3.3): https://www.psycopg.org/psycopg3/docs/
- Passing parameters: https://www.psycopg.org/psycopg3/docs/basic/params.html
- Transactions: https://www.psycopg.org/psycopg3/docs/basic/transactions.html
- Connection pools: https://www.psycopg.org/psycopg3/docs/advanced/pool.html
