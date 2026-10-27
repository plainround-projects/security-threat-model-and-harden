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
`%s` in the statement, a tuple of values (note the comma in `(note_id,)`: a one-item tuple). `fetchone()` returns a tuple or `None`. `to_note` maps columns to the `Note` dataclass using `int(str(row[0]))` and similar, because the row type is `tuple[object, ...]` and `mypy --strict` insists on checked conversions.

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
