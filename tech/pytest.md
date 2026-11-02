# pytest 9 and coverage

## What it is

**pytest** is a Python tool that finds and runs tests. A **test** is a function whose name starts with `test_`; it runs some code and uses `assert` to say what must be true. If an assert is false (or the code raises), the test **fails**; otherwise it **passes**. pytest prints which ones did what. Pinned: `pytest==9.1.1`, `pytest-cov==7.1.0` (which uses `coverage`). **Coverage** measures which lines of your code ran during the tests.

## Why this repository uses it

The lesson's claim is "every control is proven by a test, and the test fails when the control is removed". That needs tests at four levels, fast ones that need no database and slow ones that do, selected by simple commands. pytest's **fixtures** (reusable set-up code) and **markers** (labels on tests) make that practical.

## Where it appears

| Path | What it does |
| --- | --- |
| `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.coverage.*]`) | Test folder, options, marker names, coverage settings. |
| `tests/unit/` (96 tests) | Domain, application, HTTP layer over in-memory fakes, settings, logging, headers, the threat-model document. No database. |
| `tests/integration/` (20) | PostgreSQL repositories and the role limits. Marker `integration`. |
| `tests/security/` (33) | One or more tests per threat-model control. Marker `security`. |
| `tests/e2e/` (4) | The whole scenario over real HTTP against a started gunicorn. Marker `e2e`. |
| `tests/conftest.py`, `tests/fakes.py`, `tests/support.py` | Fixtures, in-memory stand-ins for ports, a cookie-keeping `Browser` helper. |
| `Makefile` | `test`, `test-security`, `test-integration`, `test-e2e`, `test-all`. |
| `scripts/prove_controls.py` | Runs chosen tests again and again with a control removed. |

## How it works underneath

1. `pytest tests/unit` walks the folder, imports every `test_*.py`, and collects functions named `test_*`.
2. For each test it looks at the **parameter names**. A parameter named like a fixture (`app`, `browser`, `owner_sql`) is filled by running that fixture function first. Fixtures are found in the test file or in `conftest.py` files up the folder tree.
3. A fixture with `yield` runs set-up before the `yield`, hands the value to the test, then runs the clean-up after the test finishes, even if it failed.
4. pytest runs the test; `assert` is rewritten at import time so a failure shows both sides of the comparison.
5. `-m integration` runs only tests carrying that marker. `-k text` selects by name.
6. With coverage, a tracer records every line (and every branch) executed; the report shows what never ran.

### Ideas you need first

- **A test.** A small function that runs part of the program and states what must be true afterwards. If the statement is false, the test fails and shows why.
- **An assertion.** `assert x == 3` raises an error when `x` is not 3. pytest turns that into a readable failure message showing both values.
- **A unit test, an integration test and an end-to-end test.** A **unit** test checks one small piece with everything around it replaced by simple stand-ins. An **integration** test checks the piece together with a real neighbor (here a real database). An **end-to-end** test runs the whole program as a user would reach it (here a real server process over real HTTP).
- **A fake (a stand-in).** A simple object with the same methods as the real thing, used so a test needs no database or network: `InMemoryUsers` stores users in a dictionary, `FakeClock` returns a time the test moves by hand.
- **A fixture.** Set-up code a test asks for by naming it as a parameter. pytest runs it first and passes in what it returns. Code after a `yield` in a fixture is clean-up.
- **A marker.** A label on tests (`@pytest.mark.security`, or `pytestmark = pytest.mark.security` for a whole file) so you can run just those with `-m security`.
- **Coverage.** A measurement of which lines of the program ran during the tests. A line that never ran has no test protecting it.

## Walkthrough of this repository's use

### Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "integration: needs PostgreSQL from docker-compose.yml (make up)",
    "security: one test per control of the threat model; needs PostgreSQL (make up)",
    "e2e: the lesson's scenario over real HTTP against a running server; needs PostgreSQL (make up)",
]
```
`testpaths` is the default search folder. `-ra` prints a summary of every non-passing outcome. `--strict-markers` makes an unknown marker (a typo) an error. Files declare `pytestmark = pytest.mark.security` once to label every test in them.

### Fixtures that build the world

```python
os.environ["APP_ENV"] = "test"
```
At the top of `tests/conftest.py`: before any settings are read, force the one environment where the `UNSAFE_*` weaknesses are accepted.

```python
@pytest.fixture(scope="session")
def settings() -> Settings:
    env = dict(os.environ)
    env.setdefault("NOTES_DB_PASSWORD", "local-only-app-password")
    env["ARGON2_TIME_COST"] = "1"
    env["ARGON2_MEMORY_KIB"] = "1024"
    return Settings.from_environment(env)
```
`scope="session"` builds it once per run. Argon2 is set to its cheapest values so the tests are fast (this is allowed only in `APP_ENV=test`).

```python
@pytest.fixture
def container(settings, owner_sql):
    owner_sql((ROOT / "sql" / "reset.sql").read_text())
    wired = build_container(settings)
    wired.database.open()
    yield wired
    wired.database.close()
```
Each test gets an emptied database (the `reset.sql` truncate), a wired application, and the pool is closed afterwards. `owner_sql` is another fixture: a direct connection as the *owner* role, so tests can look inside the database (for example to check that a hash is stored, or that a session row holds the hash and not the cookie).

```python
@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
```
Attaches a handler that renders every log record with the production JSON formatter into a string, so a test can assert that a password never appeared in the logs.

### Fakes: testing without a database

`tests/fakes.py` has in-memory classes with the same methods as the ports: `FakeClock` (time the test moves by hand), `CountingTokens` (`token-1`, `token-2`), `ReversibleHasher` (instant, not a real hash), `InMemoryUsers`, `InMemoryNotes`, `InMemorySessions`, `InMemoryThrottle`, `ListAudit`. The unit tests wire services to these. That is why the domain and application layers can be tested to 100% coverage in seconds.

### A test, line by line

```python
def test_hostile_content_is_stored_exactly_as_text(browser, owner_sql):
    browser.register()
    note_id = browser.create_note(title="It's a 'quoted' title", content=HOSTILE)
    stored = owner_sql("SELECT title, content FROM notes WHERE id = %s", (note_id,))
    assert stored == [("It's a 'quoted' title", HOSTILE)]
    assert owner_sql("SELECT count(*) FROM notes") == [(1,)]
    assert owner_sql("SELECT count(*) FROM users") == [(1,)]
```
Register a user through the real app, create a note whose text contains quotes and an injection string, read it back as the owner, and check it is exactly the same text and that nothing else changed. With `UNSAFE_SQL_CONCATENATION=1` the insert breaks and the test fails.

### Coverage gate

```make
$(PY) -m pytest tests/unit --cov=notes_app --cov-report=term
$(PY) -m coverage report --include='src/notes_app/domain/*,src/notes_app/application/*' --fail-under=95
```
```toml
[tool.coverage.run]
source = ["notes_app"]
branch = true
```
`branch = true` also counts both sides of every `if`. The second command fails the build if the domain and application folders drop below 95%. They are at 100% (317 statements, 44 branches). The whole package is lower (75% with unit tests alone) because the PostgreSQL adapters, `wsgi.py`, `demo_cli.py` and `gunicorn_conf.py` are exercised by the integration, security and e2e tests, not the unit tests.

### The four levels

| Level | Needs | Command |
| --- | --- | --- |
| unit | nothing | `make test` |
| integration | PostgreSQL | `make test-integration` |
| security | PostgreSQL | `make test-security` |
| e2e | PostgreSQL, spawns gunicorn on a free port | `make test-e2e` |

The e2e test starts the server as a subprocess the way production does, waits for `/readyz`, runs the demo scenario, sends SIGTERM and checks a clean exit.

### Every test file

Counts as pytest collects them: 96 unit tests (access 5, accounts 9, hasher 4, http_app 14, logging 4, notes_service 10, security_headers 4, sessions 11, settings 11, threat_model_document 4, throttle 5, validation 15), 20 integration tests (database 8, repositories 12), 33 security tests and 4 end-to-end tests: 153 in all. Some files collect more tests than they list functions because a **parametrized** test (one function run with several inputs, such as five forbidden SQL statements) counts once per input. Every test function is listed below; the name states the claim.

**Shared helpers.** `tests/fakes.py` has the in-memory stand-ins for the ports: `FakeClock` (a clock the test moves with `advance`), `CountingTokens` (`token-1`, `token-2`...), `ReversibleHasher` (not a real hash: `hashed:<password>`, so tests run instantly and can check what was stored), `InMemoryUsers`, `InMemoryNotes`, `InMemorySessions`, `InMemoryThrottle`, `ListAudit`. `tests/support.py` has `Browser`, a cookie-keeping client around Flask's test client (it talks to `https://localhost` so the `Secure` cookie travels), `new_username()` and `new_password()` (random per test, so no credential is ever written in a test), and the hostile string `<script>alert(1)</script> and a quote: ' OR '1'='1`. `tests/conftest.py` forces `APP_ENV=test`, builds `Settings` with cheap Argon2 settings, gives tests `owner_sql` (a connection as the owner role to look inside the database), `container` (an emptied database and a wired app), `app`, `browser`, and `captured_logs` (everything logged, in the production JSON format).

**`tests/unit/` (no database).**

| File | Tests and what each proves |
| --- | --- |
| `test_access.py` (5) | The owner has write access; a user the note is shared with can only read; everyone else gets none; the levels are ordered so write includes read; the production policy is exactly the domain rule. |
| `test_accounts.py` (9) | Registering stores a hash, never the password; a taken name is refused; a short password is refused; a correct sign-in returns the user and resets the throttle; a wrong password and an unknown user fail the same way; a malformed username is just a failed login; a throttled client is refused before any password check; a hash made with old settings is upgraded at sign-in; `get_user` works. |
| `test_hasher.py` (4) | The same password hashes differently each time and still verifies; a malformed stored value never verifies and always needs a rehash; a hash with weaker settings needs a rehash; the deliberate weakness is unsalted, so equal passwords collide. |
| `test_http_app.py` (14) | Health endpoints; sign-up, sign-in and the notes page; an anonymous visitor is redirected by page and refused by API; sign-up reports a taken name or weak password without leaking more; a wrong password and an unknown user give the same response; the fourth failure is throttled with `Retry-After`; sign-out clears the cookie and the server-side session; a POST with no session or token is refused and audited; notes through JSON and pages; the form flow creates a note and redirects; sharing gives read-only access; unknown routes and methods use one error shape; an unexpected error returns no internal detail; an oversized body is refused. |
| `test_logging.py` (4) | Sensitive field names are redacted and others kept; the formatter writes one JSON object with extras redacted; exceptions are included as text; `configure_logging` installs the JSON handler. |
| `test_notes_service.py` (7) | The owner creates, reads, updates and deletes; a stranger gets not-found for every action and the attempt is audited; a missing note and a foreign note raise the same error; a reader gets forbidden for update, delete and share; sharing with yourself or an unknown user is refused; listing shows owned and shared notes with roles; update validates new values. |
| `test_security_headers.py` (4) | The CSP allows no script and no framing; headers are added but a handler's own value wins; the cookie is host-prefixed, HttpOnly, Secure, SameSite; clearing expires it with the same attributes. |
| `test_sessions.py` (11) | Only the hash of the cookie is stored; anonymous sessions expire quickly, signed-in ones last longer; sign-in replaces the previous session and CSRF token; a session resolves until idle too long; activity extends life but not past the absolute limit; an expired session is deleted when found; unknown cookies resolve to nothing; `last_seen` is written at most once a minute; sign-out removes the session; sign-in purges expired sessions; CSRF comparison. |
| `test_settings.py` (9) | Defaults are the hardened ones; the database password is required and never printed; an unknown environment is refused; bad or too-small integers are refused; weaknesses are refused outside test and accepted in test; flags read only known truthy values; weak Argon2 settings are refused outside test; inconsistent pool and session settings are refused. |
| `test_threat_model_document.py` (4) | Every boundary has a threat; every "fixed" threat links a test that exists; ids are unique and sequential; at least one accepted risk has a reason. |
| `test_throttle.py` (5) | Below the limit no throttle; at the limit the wait lasts until the blocking failure ages out; failures outside the window are ignored; the wait is never under one second; with more failures than the limit the wait follows the newest blocking set. |
| `test_validation.py` (7) | Username is lower-cased and trimmed; outside the allow-list is refused; password length bounds; a long passphrase with spaces is accepted unchanged; titles are trimmed and one line; content keeps markup; content refuses NUL and oversize. |

**`tests/integration/` (needs `make up`).**

| File | Tests |
| --- | --- |
| `test_database.py` | Ping is true while open and false after close; a wrong password fails loudly; the application role cannot change the schema (`DROP TABLE`, `ALTER TABLE` are refused); the application role can do ordinary work. |
| `test_repositories.py` | Users are added, found and re-hashed; the unique constraint (not a lookup) refuses a duplicate name; the schema rejects a username outside the allow-list; notes are created, read, updated and deleted with their shares; the visible list has owned and shared notes with roles, newest first; the database also refuses an over-long title; sessions round-trip and touch; purging removes only expired sessions; the throttle counts per key, ages out and resets; recording a failure prunes rows that left every window; an audit event is stored with its detail; a failing audit write is logged and does not fail the request. |

**`tests/security/` (needs `make up`; one or more per threat).**

| File | Tests |
| --- | --- |
| `test_audit.py` | A denied access writes a log line and an audit row; sign-up, sign-in, failure and sign-out are audited; a forged request is audited; audit detail holds only ids and reasons; the application role cannot change or delete audit rows; even the owner role cannot rewrite history. |
| `test_authentication.py` | Repeated failures are throttled with `Retry-After` and audited; a correct password is also refused while throttled; a different client address is not throttled by someone else's failures; the throttle stores neither the username nor the address; an unknown user and a wrong password look identical. |
| `test_authorization.py` | User A cannot read, update or delete user B's note; changing the id in the URL reaches no foreign note; a foreign note and a missing note are indistinguishable; an `owner` in the request body is ignored; every notes route refuses a request with no session; a shared-with user can read but not change or share; revoking access takes effect on the next request. |
| `test_injection.py` | Hostile content is stored exactly as text; it is rendered as inert text; SQL metacharacters in the sign-in form are just a failed sign-in; a note with `%` and a backslash round-trips. |
| `test_passwords.py` | Passwords are salted and not logged; the login response and pages never echo the password. |
| `test_session.py` | Cookie flags; security headers on every response; a state-changing request without a CSRF token is refused; another session's token does not work; the session id changes at sign-in; sign-out ends the session on the server; a session past expiry is refused; an idle session is refused; an unknown or malformed cookie is refused. |

**`tests/e2e/test_scenario.py` (needs `make up`).** It picks a free port (`socket.bind(("127.0.0.1", 0))` lets the operating system choose), starts the real server as a subprocess (`python -m gunicorn -c python:... "notes_app.interfaces.wsgi:build_app()"`) with two workers, waits up to 180 seconds for `/readyz`, and runs: the whole demo scenario against it (every step must pass); `SIGTERM` makes it exit 0 with `Handling signal: term` and `database pool closed` in its log; the server refuses to start with a deliberate weakness outside the test environment; the server refuses to start without a database password. A `try/finally` stops the server even when a check fails, so no process is left behind.

### Line by line: `tests/conftest.py`

A file named `conftest.py` is read by pytest automatically; fixtures defined here are available to every test under `tests/` without importing them. A **fixture** is a function marked `@pytest.fixture` whose return value is handed to any test that has a parameter with the same name.

```python
"""Fixtures. APP_ENV is forced to ``test`` before any settings are read, the only environment where the deliberate
weaknesses (UNSAFE_* variables, used by ``make prove``) are accepted."""
```

The docstring: `APP_ENV` is forced to `test` before any settings are read, because that is the only environment in which the deliberate weaknesses (the `UNSAFE_*` variables used by `make prove`) are accepted.

```python
from __future__ import annotations

import io
import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
```

Type hints as text; imports of `io` (in-memory streams), `logging`, `os`, `Callable` and `Iterator`, `Path` and `Any`.

```python
import psycopg
import pytest
from flask import Flask
```

`psycopg` (to open a database connection as the owner), `pytest` and Flask's `Flask` type.

```python
from notes_app.infrastructure.logging import JsonFormatter
from notes_app.infrastructure.settings import Settings
from notes_app.interfaces.composition import Container, build_container
from notes_app.interfaces.http.app import create_app
from tests.support import Browser
```

Imports of the JSON log formatter, `Settings`, the container builder, the application factory and the test `Browser` helper.

```python
os.environ["APP_ENV"] = "test"
ROOT = Path(__file__).resolve().parent.parent
```

`os.environ["APP_ENV"] = "test"` runs when this file is loaded, before any test. `ROOT` is the repository folder.

```python
@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings from the environment (``make`` exports .env), with fast argon2 parameters for speed."""
    env = dict(os.environ)
    env.setdefault("NOTES_DB_PASSWORD", "local-only-app-password")
    env["ARGON2_TIME_COST"] = "1"
    env["ARGON2_MEMORY_KIB"] = "1024"
    return Settings.from_environment(env)
```

The `settings` fixture has `scope="session"`: it is built once for the whole test run, not once per test. It copies the environment (`make` exports `.env`), sets a default app password with `setdefault` (used only if none is set) and overrides the argon2 cost to 1 iteration and 1024 KiB so hashing is fast in tests.

```python
def _owner_connection() -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=os.environ.get("NOTES_DB_HOST", "localhost"),
        port=int(os.environ.get("NOTES_DB_PORT", "5471")),
        dbname=os.environ.get("POSTGRES_DB", "notes"),
        user=os.environ.get("POSTGRES_USER", "notes_owner"),
        password=os.environ.get("POSTGRES_PASSWORD", "local-only-owner-password"),
        autocommit=True,
    )
```

`_owner_connection` opens a connection as the owner role from environment variables with local defaults. `autocommit=True` makes every statement commit at once.

```python
@pytest.fixture
def owner_sql() -> Iterator[Callable[..., list[tuple[Any, ...]]]]:
    """Run SQL as the owner role (the test's window into the database); returns the rows, if any."""
    connection = _owner_connection()

    def run(statement: str, params: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
        cursor = connection.execute(statement, params)
        return cursor.fetchall() if cursor.description else []

    yield run
    connection.close()
```

The `owner_sql` fixture is the test's window into the database as the owner. It opens a connection and defines an inner function `run(statement, params)` that executes SQL and returns the rows if the statement produced any (`cursor.description` is `None` for statements without a result). `yield run` hands the function to the test; the code after `yield` closes the connection after the test.

```python
@pytest.fixture
def container(settings: Settings, owner_sql: Callable[..., Any]) -> Iterator[Container]:
    """The wired application against an emptied database."""
    owner_sql((ROOT / "sql" / "reset.sql").read_text())
    wired = build_container(settings)
    wired.database.open()
    yield wired
    wired.database.close()
```

The `container` fixture empties the database with `sql/reset.sql` (as the owner), builds the real wired application, opens its pool, hands it to the test and closes the pool afterwards.

```python
@pytest.fixture
def app(container: Container) -> Flask:
    return create_app(container)
```

The `app` fixture creates the Flask application around the container.

```python
@pytest.fixture
def browser(app: Flask) -> Browser:
    return Browser(app)
```

The `browser` fixture wraps the app in the cookie-keeping test client.

```python
@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    """Everything the application logs, rendered as the production JSON formatter renders it."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield stream
    root.removeHandler(handler)
    root.setLevel(previous_level)
```

The `captured_logs` fixture adds a handler to the root logger that writes to an in-memory stream with the production JSON formatter, sets the level to DEBUG, hands the stream to the test, and afterwards removes the handler and restores the earlier level. Tests use it to prove what was logged, and what was not.

### Line by line: `tests/support.py`

```python
"""Helpers shared by the HTTP-level tests: a cookie-keeping client that behaves like a browser on https://localhost."""
```

The docstring: helpers shared by the HTTP-level tests, a client that keeps cookies and behaves like a browser on `https://localhost`.

```python
from __future__ import annotations

import re
import secrets
from typing import Any

from flask import Flask
from werkzeug.test import TestResponse

from notes_app.interfaces.http.security import CSRF_HEADER, SESSION_COOKIE
```

Imports: `re`, `secrets`, `Any`, `Flask`, Werkzeug's `TestResponse` and the cookie and header names from the application.

```python
_CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')
HOSTILE = "<script>alert(1)</script> and a quote: ' OR '1'='1"
```

`_CSRF_FIELD` finds the CSRF token in a page's hidden input. `HOSTILE` is the attack text (a script tag and a SQL-style quote) used by the injection tests.

```python
def new_password() -> str:
    """A fresh generated password, so no credential is ever written in a test."""
    return secrets.token_urlsafe(18)
```

`new_password` returns a random URL-safe password, so no credential is ever written in a test file.

```python
def new_username(prefix: str = "user") -> str:
    """A unique valid username."""
    return f"{prefix}_{secrets.token_hex(4)}"
```

`new_username` returns a valid unique name: the prefix, an underscore and four random bytes in hexadecimal.

```python
class Browser:
    """One person's browser: its own cookie jar, talking to the app over https on localhost."""

    def __init__(self, app: Flask, remote_addr: str = "127.0.0.1") -> None:
        self.client = app.test_client()
        self.remote_addr = remote_addr
```

`Browser` is one person's browser. It has its own cookie jar (`app.test_client()` makes a client that calls the app directly in memory) and a fake client address.

```python
    def request(self, method: str, path: str, **kwargs: Any) -> TestResponse:
        kwargs.setdefault("base_url", "https://localhost")
        kwargs.setdefault("environ_base", {"REMOTE_ADDR": self.remote_addr})
        return self.client.open(path, method=method, **kwargs)
```

`request` sends a request over `https://localhost` (so Secure cookies are sent) with `REMOTE_ADDR` set; `setdefault` keeps any value a test passes.

```python
    def get(self, path: str, **kwargs: Any) -> TestResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> TestResponse:
        return self.request("POST", path, **kwargs)
```

Shortcuts `get` and `post`.

```python
    def csrf_token(self) -> str:
        """The CSRF token of the current session, read from a form the way a browser would."""
        match = _CSRF_FIELD.search(self.get("/login").get_data(as_text=True))
        assert match is not None, "the sign-in page carries a CSRF token"
        return match.group(1)
```

`csrf_token` loads the sign-in page and reads the token from the form, the way a browser would; the `assert` message says what is expected.

```python
    def api(self, method: str, path: str, *, json: Any = None, csrf: str | None = "auto") -> TestResponse:
        """A JSON request. ``csrf="auto"`` sends the session's token, ``None`` sends none, anything else sends it."""
        headers = {"Accept": "application/json"}
        token = self.csrf_token() if csrf == "auto" else csrf
        if token is not None:
            headers[CSRF_HEADER] = token
        return self.request(method, path, json=json, headers=headers)
```

`api` sends a JSON request. `csrf="auto"` sends the session's token, `None` sends none, anything else sends that text. The `*` makes `json` and `csrf` keyword-only.

```python
    def sign_up(self, username: str, password: str) -> TestResponse:
        data = {"username": username, "password": password, "csrf_token": self.csrf_token()}
        return self.post("/signup", data=data)
```

`sign_up` posts the form with a fresh CSRF token.

```python
    def sign_in(self, username: str, password: str) -> TestResponse:
        data = {"username": username, "password": password, "csrf_token": self.csrf_token()}
        return self.post("/login", data=data)
```

`sign_in` does the same for the login form.

```python
    def register(self, prefix: str = "user") -> tuple[str, str]:
        """Sign up and sign in a new user; returns the username and the generated password."""
        username, password = new_username(prefix), new_password()
        assert self.sign_up(username, password).status_code == 303
        assert self.sign_in(username, password).status_code == 303
        return username, password
```

`register` signs up and signs in a new generated user; each must answer 303 (redirect). It returns the name and the password.

```python
    def session_cookie(self) -> str | None:
        cookie = self.client.get_cookie(SESSION_COOKIE, domain="localhost")
        return None if cookie is None else cookie.value
```

`session_cookie` returns the session cookie's value from the jar or `None`.

```python
    def create_note(self, title: str = "A note", content: str = "some text") -> int:
        response = self.api("POST", "/notes", json={"title": title, "content": content})
        assert response.status_code == 201, response.get_data(as_text=True)
        return int(response.get_json()["id"])
```

`create_note` posts a note through the API, asserts 201 and returns the new id.

### Line by line: `tests/fakes.py`

```python
"""In-memory stand-ins for the ports: the domain, application and HTTP layer are tested without a database."""
```

The docstring: in-memory stand-ins for the ports, so the domain, application and HTTP layers are tested without a database. A stand-in that mimics an interface is a **fake**.

```python
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from notes_app.domain.errors import UsernameTakenError
from notes_app.domain.models import AuditEvent, Note, NoteRole, Session, User, VisibleNote
```

Imports: `replace` (copies a frozen dataclass with changed fields), time types, the taken-name error and the models.

```python
START = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
```

`START` is a fixed moment (27 October 2026, 09:00 UTC) that tests use as "now".

```python
class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime = START) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)
```

`FakeClock` is a clock the test moves by hand: `now()` returns the stored time and `advance(minutes=5)` adds a `timedelta` built from the keyword arguments.

```python
class CountingTokens:
    """Predictable tokens: token-1, token-2, ..."""

    def __init__(self) -> None:
        self._count = 0

    def new_token(self) -> str:
        self._count += 1
        return f"token-{self._count}"
```

`CountingTokens` returns `token-1`, `token-2`, `token-3` in order, so tests know which token each session gets.

```python
class ReversibleHasher:
    """Not a real hash: lets service tests run instantly and check what was stored."""

    def __init__(self) -> None:
        self.dummy_calls = 0
        self.rehash_wanted = False

    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password: str, encoded: str) -> bool:
        return encoded == f"hashed:{password}"

    def needs_rehash(self, encoded: str) -> bool:
        return self.rehash_wanted

    def spend_equal_effort(self, password: str) -> None:
        self.dummy_calls += 1
```

`ReversibleHasher` is not a real hash. `hash` returns `hashed:<password>` and `verify` compares with that. It counts calls of `spend_equal_effort` in `dummy_calls`, and `rehash_wanted` lets a test make `needs_rehash` return true. It makes service tests instant and lets them look at what was stored.

```python
class InMemoryUsers:
    def __init__(self) -> None:
        self.rows: dict[int, User] = {}

    def add(self, username: str, password_hash: str) -> User:
        if any(user.username == username for user in self.rows.values()):
            raise UsernameTakenError(username)
        user = User(id=len(self.rows) + 1, username=username, password_hash=password_hash)
        self.rows[user.id] = user
        return user

    def by_username(self, username: str) -> User | None:
        return next((user for user in self.rows.values() if user.username == username), None)

    def by_id(self, user_id: int) -> User | None:
        return self.rows.get(user_id)

    def update_password_hash(self, user_id: int, password_hash: str) -> None:
        self.rows[user_id] = replace(self.rows[user_id], password_hash=password_hash)
```

`InMemoryUsers` keeps users in a dictionary by id. `add` refuses a duplicate name with the same error the database adapter raises and numbers users from 1; `by_username`, `by_id` and `update_password_hash` (which replaces the user with a copy) behave like the real repository.

```python
class InMemoryNotes:
    def __init__(self, users: InMemoryUsers, clock: FakeClock) -> None:
        self._users = users
        self._clock = clock
        self.notes: dict[int, Note] = {}
        self.shares: dict[int, set[int]] = {}

    def add(self, owner_id: int, title: str, content: str) -> Note:
        now = self._clock.now()
        note = Note(len(self.notes) + 1, owner_id, title, content, now, now)
        self.notes[note.id] = note
        return note

    def get(self, note_id: int) -> Note | None:
        return self.notes.get(note_id)

    def shared_with(self, note_id: int) -> frozenset[int]:
        return frozenset(self.shares.get(note_id, set()))

    def update(self, note_id: int, title: str, content: str) -> Note:
        note = replace(self.notes[note_id], title=title, content=content, updated_at=self._clock.now())
        self.notes[note_id] = note
        return note

    def delete(self, note_id: int) -> None:
        self.notes.pop(note_id, None)
        self.shares.pop(note_id, None)

    def share(self, note_id: int, user_id: int) -> None:
        self.shares.setdefault(note_id, set()).add(user_id)

    def list_visible(self, user_id: int) -> list[VisibleNote]:
        visible = []
        for note in self.notes.values():
            owner = self._users.rows[note.owner_id]
            if note.owner_id == user_id:
                visible.append(VisibleNote(note, NoteRole.OWNER, owner.username))
            elif user_id in self.shares.get(note.id, set()):
                visible.append(VisibleNote(note, NoteRole.READER, owner.username))
        return visible
```

`InMemoryNotes` keeps notes by id and shares as a dictionary from note id to a set of user ids. `add` stamps both times with the fake clock; `update` replaces the note with a copy; `delete` removes the note and its shares; `share` adds to the set (a set makes it idempotent); `list_visible` loops over notes and adds a `VisibleNote` with role `OWNER` for the user's own and `READER` for shared ones.

```python
class InMemorySessions:
    def __init__(self) -> None:
        self.rows: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        self.rows[session.token_hash] = session

    def get(self, token_hash: str) -> Session | None:
        return self.rows.get(token_hash)

    def touch(self, token_hash: str, seen_at: datetime) -> None:
        self.rows[token_hash] = replace(self.rows[token_hash], last_seen_at=seen_at)

    def delete(self, token_hash: str) -> None:
        self.rows.pop(token_hash, None)

    def purge_expired(self, now: datetime) -> int:
        expired = [key for key, session in self.rows.items() if session.expires_at <= now]
        for key in expired:
            del self.rows[key]
        return len(expired)
```

`InMemorySessions` keeps sessions by token hash; `purge_expired` removes those whose expiry is at or before now and returns how many.

```python
class ListAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)

    def actions(self) -> list[str]:
        return [event.action.value for event in self.events]
```

`ListAudit` appends events to a list and `actions()` returns their action names.

```python
class RecordingThrottle:
    """Throttle double: records calls and can be told to refuse."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.resets: list[str] = []
        self.refuse_with: int | None = None

    def check(self, key: str, now: datetime) -> None:
        from notes_app.domain.errors import LoginThrottledError

        if self.refuse_with is not None:
            raise LoginThrottledError(self.refuse_with)

    def record_failure(self, key: str, now: datetime) -> None:
        self.failures.append(key)

    def reset(self, key: str) -> None:
        self.resets.append(key)
```

`RecordingThrottle` records the keys of failures and resets, and `refuse_with` makes `check` raise the throttled error with that number of seconds.

```python
class InMemoryThrottle:
    """The same rule as the PostgreSQL throttle, kept in a dict, for tests that need real counting."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self._max = max_failures
        self._window = timedelta(seconds=window_seconds)
        self._failures: dict[str, list[datetime]] = {}

    def check(self, key: str, now: datetime) -> None:
        from notes_app.domain.errors import LoginThrottledError
        from notes_app.domain.throttle import retry_after_seconds

        wait = retry_after_seconds(self._failures.get(key, []), now=now, max_failures=self._max, window=self._window)
        if wait is not None:
            raise LoginThrottledError(wait)

    def record_failure(self, key: str, now: datetime) -> None:
        self._failures.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
```

`InMemoryThrottle` applies the same pure rule as the PostgreSQL throttle but keeps the failure times in a dictionary, for tests that need real counting.

### Line by line: `tests/unit/test_access.py`

```python
from notes_app.application.policy import OwnerOrSharedPolicy
from notes_app.domain.access import Access, access_to_note
```

Imports of the production policy and the domain rule.

```python
def test_owner_has_write_access():
    assert access_to_note(owner_id=1, shared_with=set(), user_id=1) is Access.WRITE
```

The owner of note 1 gets `WRITE`. `is` compares identity, which works for enumeration members.

```python
def test_user_the_note_is_shared_with_can_only_read():
    assert access_to_note(owner_id=1, shared_with={2}, user_id=2) is Access.READ
```

A user in the shared set gets only `READ`.

```python
def test_everyone_else_has_no_access():
    assert access_to_note(owner_id=1, shared_with={2}, user_id=3) is Access.NONE
```

A user in neither gets `NONE`.

```python
def test_access_levels_are_ordered_so_write_includes_read():
    assert Access.WRITE > Access.READ > Access.NONE
```

`Access.WRITE > Access.READ > Access.NONE`: the levels are ordered, so write includes read.

```python
def test_the_production_policy_is_the_domain_rule():
    policy = OwnerOrSharedPolicy()
    assert policy.access(owner_id=1, shared_with=frozenset({2}), user_id=2) is Access.READ
```

The production policy gives the same answer as the pure domain function.

### Line by line: `tests/unit/test_throttle.py`

```python
from datetime import timedelta

from notes_app.domain.throttle import retry_after_seconds
from tests.fakes import START
```

Imports: `timedelta`, the rule and the fixed `START` time.

```python
WINDOW = timedelta(minutes=10)


def wait(failures, now=START, max_failures=3):
    return retry_after_seconds(failures, now=now, max_failures=max_failures, window=WINDOW)
```

`WINDOW` is ten minutes. `wait(...)` is a small helper that calls the rule with a window and a default limit of 3 failures.

```python
def test_failures_below_the_limit_do_not_throttle():
    assert wait([START, START]) is None
    assert wait([]) is None
```

Two failures, or none, are below the limit of 3: no wait (`None`).

```python
def test_the_limit_throttles_until_the_blocking_failure_ages_out():
    failures = [START, START + timedelta(seconds=1), START + timedelta(seconds=2)]
    assert wait(failures, now=START + timedelta(seconds=10)) == 591
```

Three failures at 0, 1 and 2 seconds, checked at 10 seconds: the blocking one is the first, which ages out at 600 seconds, so the wait is 600 minus 10 plus one extra second, 591.

```python
def test_failures_outside_the_window_are_ignored():
    old = [START - timedelta(minutes=11)] * 5
    assert wait(old) is None
    assert wait([*old, START]) is None
```

Five failures eleven minutes old are outside the window and ignored; adding one fresh failure still leaves only one live.

```python
def test_the_wait_is_never_less_than_one_second():
    failures = [START - timedelta(minutes=10) + timedelta(milliseconds=1)] * 3
    assert wait(failures) == 1
```

Three failures that leave the window in one millisecond still give a wait of 1: never less than one second.

```python
def test_with_more_failures_than_the_limit_the_wait_follows_the_newest_blocking_set():
    failures = [START + timedelta(seconds=n) for n in range(5)]
    assert wait(failures, now=START + timedelta(seconds=5)) == 598
```

Five failures at 0 to 4 seconds, checked at 5 seconds, with a limit of 3: the blocking failure is the third (2 seconds), so the wait is 600 minus 3 plus 1, 598.

### Line by line: `tests/unit/test_hasher.py`

```python
from argon2 import PasswordHasher

from notes_app.infrastructure.argon2_hasher import Argon2PasswordHasher
from notes_app.infrastructure.weaknesses.unsalted_sha256_hasher import UnsaltedSha256Hasher
```

Imports: the raw `PasswordHasher` of argon2 (to make an old-style hash), the production hasher and the weak one.

```python
FAST = {"time_cost": 1, "memory_kib": 1024, "parallelism": 1}
```

`FAST` is a dictionary of cheap parameters, unpacked into the constructor with `**FAST`.

```python
def test_the_same_password_hashes_differently_each_time_and_verifies():
    hasher = Argon2PasswordHasher(**FAST)
    first, second = hasher.hash("correct horse battery staple"), hasher.hash("correct horse battery staple")
    assert first != second
    assert first.startswith("$argon2id$")
    assert hasher.verify("correct horse battery staple", first)
    assert not hasher.verify("another passphrase entirely", first)
```

Hashing the same passphrase twice gives two different strings (a random salt each time), both start with `$argon2id$`, the right password verifies and a different one does not.

```python
def test_a_malformed_stored_value_never_verifies_and_always_needs_a_rehash():
    hasher = Argon2PasswordHasher(**FAST)
    assert not hasher.verify("anything", "not-a-hash")
    assert hasher.needs_rehash("not-a-hash")
    hasher.spend_equal_effort("anything")
```

A value that is not a hash never verifies and always "needs a rehash"; `spend_equal_effort` runs without error.

```python
def test_a_hash_made_with_weaker_parameters_needs_a_rehash():
    old = PasswordHasher(time_cost=1, memory_cost=512, parallelism=1).hash("pw")
    assert Argon2PasswordHasher(**FAST).needs_rehash(old)
    assert not Argon2PasswordHasher(**FAST).needs_rehash(Argon2PasswordHasher(**FAST).hash("pw"))
```

A hash made with 512 KiB of memory (weaker than the 1024 KiB parameters) needs a rehash; a hash made with the current parameters does not.

```python
def test_the_deliberate_weakness_is_unsalted_so_equal_passwords_collide():
    weak = UnsaltedSha256Hasher()
    assert weak.hash("pw") == weak.hash("pw")
    assert weak.verify("pw", weak.hash("pw"))
    assert not weak.verify("other", weak.hash("pw"))
    assert not weak.needs_rehash("x")
    weak.spend_equal_effort("pw")
```

The weak hasher is unsalted, so equal passwords collide, and it verifies by comparing digests, never needs a rehash, and its `spend_equal_effort` does nothing.

### Line by line: `tests/unit/test_logging.py`

```python
import io
import json
import logging
```

Standard modules: `io` (in-memory streams), `json`, `logging`.

```python
from notes_app.infrastructure.logging import REDACTED, JsonFormatter, configure_logging, redact
```

Imports of the replacement text, the JSON formatter, the logging setup and `redact`.

```python
def test_sensitive_field_names_are_redacted_and_others_are_kept():
    fields = {
        "password": "p",
        "new_password": "p",
        "csrf_token": "t",
        "Authorization": "Bearer x",
        "cookie": "c",
        "session_id": "s",
        "api_key": "k",
        "client_secret": "s",
        "user_id": 7,
        "path": "/notes/1",
    }
    cleaned = redact(fields)
    assert {key for key, value in cleaned.items() if value == REDACTED} == set(fields) - {"user_id", "path"}
    assert cleaned["user_id"] == 7
```

Ten fields are passed to `redact`: eight with sensitive-looking names (`password`, `new_password`, `csrf_token`, `Authorization`, `cookie`, `session_id`, `api_key`, `client_secret`) and two normal ones (`user_id`, `path`). The set of redacted keys must equal all keys except `user_id` and `path` (`set(fields) - {...}` is set subtraction), and `user_id` keeps its number 7.

```python
def test_the_formatter_writes_one_json_object_with_extra_fields_redacted():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.json")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
```

A logger is wired to an in-memory stream with the JSON formatter; `propagate = False` stops records from going to the root logger as well.

```python
    logger.info("signed in", extra={"user_id": 7, "password": "hunter2-hunter2"})
    line = json.loads(stream.getvalue())
    assert line["message"] == "signed in"
    assert line["level"] == "INFO"
    assert line["user_id"] == 7
    assert line["password"] == REDACTED
    assert "hunter2" not in stream.getvalue()
```

It logs `signed in` with two extra fields. The single output line is parsed as JSON: the message and level are right, `user_id` is 7, `password` is redacted and the text `hunter2` appears nowhere.

```python
def test_exceptions_are_included_as_text():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.exc")
    logger.handlers[:] = [handler]
    logger.propagate = False
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("failed")
    assert "ValueError: boom" in json.loads(stream.getvalue())["exception"]
```

Logging an exception with `logger.exception` puts text containing `ValueError: boom` in the `exception` field.

```python
def test_configure_logging_installs_the_json_handler_on_the_root_logger():
    configure_logging("WARNING")
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
```

`configure_logging("WARNING")` sets the root level to WARNING and installs a handler whose formatter is the JSON formatter.

### Line by line: `tests/unit/test_validation.py`

```python
import pytest

from notes_app.domain.errors import InvalidInputError
from notes_app.domain.validation import (
    CONTENT_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    validate_note_content,
    validate_note_title,
    validate_password,
    validate_username,
)
```

Imports: `pytest`, the error and the validators and limits.

```python
def test_username_is_lowercased_and_trimmed():
    assert validate_username("  Alice_01 ") == "alice_01"
```

`"  Alice_01 "` becomes `alice_01`: trimmed and lower-cased.

```python
@pytest.mark.parametrize("raw", ["ab", "a" * 33, "has space", "semi;colon", "quote'", "ünicode", ""])
def test_username_outside_the_allow_list_is_refused(raw):
    with pytest.raises(InvalidInputError) as error:
        validate_username(raw)
    assert error.value.field == "username"
```

`parametrize` runs one test for each of seven bad usernames: too short, 33 characters, with a space, with a semicolon, with a quote, with a non-ASCII letter and empty. Each raises `InvalidInputError` for the field `username`. It checks the allow-list rule.

```python
@pytest.mark.parametrize("raw", ["short", "x" * 129, ""])
def test_password_length_bounds_are_enforced(raw):
    with pytest.raises(InvalidInputError):
        validate_password(raw)
```

Passwords `short` (5 characters), 129 characters and empty are refused.

```python
def test_a_long_passphrase_with_spaces_is_accepted_unchanged():
    passphrase = "correct horse battery staple"
    assert validate_password(passphrase) == passphrase
```

A passphrase with spaces is accepted unchanged: no composition rules and no trimming.

```python
def test_title_is_trimmed_and_must_be_one_line():
    assert validate_note_title("  Plan  ") == "Plan"
    for bad in ["", "   ", "x" * (TITLE_MAX_LENGTH + 1), "two\nlines", "carriage\rreturn", "nul\x00"]:
        with pytest.raises(InvalidInputError):
            validate_note_title(bad)
```

A title is trimmed; six bad titles are refused: empty, only spaces, 121 characters, with a newline, with a carriage return and with a NUL character.

```python
def test_content_keeps_markup_because_output_encoding_handles_it():
    hostile = "<script>alert(1)</script> and a quote: ' OR '1'='1"
    assert validate_note_content(hostile) == hostile
```

Hostile markup is kept as is in content, because the output encoding is what makes it safe.

```python
def test_content_refuses_nul_and_oversize():
    with pytest.raises(InvalidInputError):
        validate_note_content("a\x00b")
    with pytest.raises(InvalidInputError):
        validate_note_content("x" * (CONTENT_MAX_LENGTH + 1))
```

Content with a NUL character, or one character over the limit, is refused.

### Line by line: `tests/unit/test_settings.py`

```python
import pytest

from notes_app.infrastructure.settings import ConfigError, Settings, Weaknesses
```

Imports of `pytest` and the settings classes.

```python
BASE = {"NOTES_DB_PASSWORD": "x"}
```

`BASE` is the minimal valid environment: only the database password.

```python
def test_defaults_are_the_hardened_ones():
    settings = Settings.from_environment(BASE)
    assert settings.app_env == "production"
    assert settings.weaknesses.enabled() == ()
    assert settings.argon2_time_cost >= 2
    assert settings.argon2_memory_kib >= 19_456
    assert settings.session.idle_seconds == 1800
```

With only that, the environment is `production`, no weakness is on, argon2 is at least the OWASP minimum (2 iterations, 19,456 KiB) and the idle session is 1,800 seconds. The defaults are the hardened ones.

```python
def test_the_database_password_is_required_and_never_printed():
    with pytest.raises(ConfigError, match="NOTES_DB_PASSWORD"):
        Settings.from_environment({})
    settings = Settings.from_environment({"NOTES_DB_PASSWORD": "super-secret-value"})
    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" in settings.database.conninfo()
```

No environment gives `ConfigError` mentioning `NOTES_DB_PASSWORD` (`match` searches the message as a regular expression). With a password, the printed form of the settings does not contain it, while `conninfo()` does.

```python
def test_an_unknown_environment_name_is_refused():
    with pytest.raises(ConfigError, match="APP_ENV"):
        Settings.from_environment({**BASE, "APP_ENV": "staging"})
```

`APP_ENV=staging` is refused, naming `APP_ENV`.

```python
@pytest.mark.parametrize("name", ["APP_PORT", "NOTES_DB_PORT", "LOGIN_MAX_FAILURES"])
def test_a_non_numeric_or_too_small_integer_is_refused(name):
    with pytest.raises(ConfigError, match=name):
        Settings.from_environment({**BASE, name: "abc"})
    with pytest.raises(ConfigError, match=name):
        Settings.from_environment({**BASE, name: "0"})
```

For three numeric settings, `abc` is refused and `0` is refused (the minimum is 1).

```python
def test_a_deliberate_weakness_is_refused_outside_the_test_environment():
    for app_env in ("production", "development"):
        with pytest.raises(ConfigError, match="only accepted when APP_ENV=test"):
            Settings.from_environment({**BASE, "APP_ENV": app_env, "UNSAFE_SKIP_CSRF": "1"})
```

A weakness switched on in `production` or `development` is refused with the message "only accepted when APP_ENV=test".

```python
def test_a_deliberate_weakness_is_accepted_in_the_test_environment():
    settings = Settings.from_environment(
        {**BASE, "APP_ENV": "test", "UNSAFE_SKIP_CSRF": "true", "UNSAFE_SKIP_ROTATION": "1"}
    )
    assert settings.weaknesses.enabled() == ("skip_csrf",)
```

In `test` it is accepted. The environment has `UNSAFE_SKIP_CSRF=true` and an unknown `UNSAFE_SKIP_ROTATION=1`; only the known one shows up in `enabled()`, which returns a tuple.

```python
def test_weakness_flags_read_only_known_truthy_values():
    weaknesses = Weaknesses.from_environment({"UNSAFE_SQL_CONCATENATION": "0", "UNSAFE_RAW_NOTE_OUTPUT": "yes"})
    assert weaknesses.enabled() == ("raw_note_output",)
```

Only truthy texts turn a weakness on: `0` leaves SQL concatenation off, `yes` turns raw output on.

```python
def test_argon2_parameters_below_the_owasp_minimum_are_refused_outside_tests():
    with pytest.raises(ConfigError, match="argon2"):
        Settings.from_environment({**BASE, "ARGON2_MEMORY_KIB": "1024"})
    assert Settings.from_environment({**BASE, "APP_ENV": "test", "ARGON2_MEMORY_KIB": "1024"}).argon2_memory_kib == 1024
```

1024 KiB of argon2 memory is refused in production with a message mentioning argon2, but accepted in `test` where the stored value is 1024.

```python
def test_inconsistent_pool_and_session_settings_are_refused():
    with pytest.raises(ConfigError, match="POOL"):
        Settings.from_environment({**BASE, "NOTES_DB_POOL_MIN": "9", "NOTES_DB_POOL_MAX": "2"})
    with pytest.raises(ConfigError, match="ANONYMOUS"):
        Settings.from_environment({**BASE, "ANONYMOUS_SESSION_SECONDS": "99999"})
```

A pool minimum of 9 above a maximum of 2 is refused (message mentions POOL), and an anonymous session lifetime longer than the absolute one is refused (message mentions ANONYMOUS).

### Line by line: `tests/unit/test_accounts.py`

```python
import pytest

from notes_app.application.accounts import AccountService
from notes_app.domain.errors import (
    AuthenticationFailedError,
    InvalidInputError,
    LoginThrottledError,
    UsernameTakenError,
)
from tests.fakes import FakeClock, InMemoryUsers, ListAudit, RecordingThrottle, ReversibleHasher
```

Imports of `pytest`, the service and the three errors, and the fakes.

```python
PASSWORD = "a long enough passphrase"
```

`PASSWORD` is a valid passphrase constant for tests only.

```python
@pytest.fixture
def parts():
    users, hasher, throttle, audit = InMemoryUsers(), ReversibleHasher(), RecordingThrottle(), ListAudit()
    return users, hasher, throttle, audit, AccountService(users, hasher, throttle, audit, FakeClock())
```

The `parts` fixture builds the fakes (users, hasher, recording throttle, audit list) and the service with a fake clock, and returns them together so a test can unpack what it needs. `*_, service = parts` takes just the last item.

```python
def test_register_stores_a_hash_never_the_password(parts):
    users, hasher, _, audit, service = parts
    user = service.register("Alice", PASSWORD, "10.0.0.1")
    assert user.username == "alice"
    assert users.by_username("alice").password_hash == hasher.hash(PASSWORD)
    assert users.by_username("alice").password_hash != PASSWORD
    assert audit.actions() == ["signup"]
```

Registering `Alice` stores the lower-case name and a hash that equals what the fake hasher gives and is not the password, and writes exactly one `signup` audit row.

```python
def test_register_refuses_a_taken_username(parts):
    *_, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    with pytest.raises(UsernameTakenError):
        service.register("ALICE", PASSWORD, "10.0.0.1")
```

A second sign-up of `ALICE` raises `UsernameTakenError`: names are canonicalized first.

```python
def test_register_refuses_a_short_password(parts):
    *_, service = parts
    with pytest.raises(InvalidInputError):
        service.register("alice", "short", "10.0.0.1")
```

A 5-character password is refused with `InvalidInputError`.

```python
def test_authenticate_returns_the_user_and_resets_the_throttle(parts):
    _, _, throttle, audit, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    user = service.authenticate("alice", PASSWORD, "10.0.0.1")
    assert user.username == "alice"
    assert throttle.resets == ["10.0.0.1|alice"]
    assert audit.actions() == ["signup", "login.success"]
```

A correct sign-in returns the user, resets the throttle for the key `10.0.0.1|alice` and writes `signup` then `login.success`.

```python
def test_wrong_password_and_unknown_user_fail_the_same_way(parts):
    _, hasher, throttle, audit, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    with pytest.raises(AuthenticationFailedError) as wrong_password:
        service.authenticate("alice", "wrong password here", "10.0.0.1")
    with pytest.raises(AuthenticationFailedError) as unknown_user:
        service.authenticate("nobody", PASSWORD, "10.0.0.1")
    assert str(wrong_password.value) == str(unknown_user.value)
    assert hasher.dummy_calls == 1  # the unknown user still cost one hash verification
    assert len(throttle.failures) == 2
    assert audit.actions()[-2:] == ["login.failure", "login.failure"]
```

A wrong password and an unknown user raise errors with identical messages, the fake hasher shows exactly one dummy verification (for the unknown user), both failures were counted by the throttle and the last two audit rows are `login.failure`.

```python
def test_a_malformed_username_is_just_a_failed_login(parts):
    *_, service = parts
    with pytest.raises(AuthenticationFailedError):
        service.authenticate("x'; DROP TABLE users;--", PASSWORD, "10.0.0.1")
```

A name with SQL characters is just a failed login, not a crash.

```python
def test_a_throttled_client_is_refused_before_any_password_check(parts):
    _, hasher, throttle, audit, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    throttle.refuse_with = 42
    with pytest.raises(LoginThrottledError) as error:
        service.authenticate("alice", PASSWORD, "10.0.0.1")
    assert error.value.retry_after_seconds == 42
    assert hasher.dummy_calls == 0
    assert audit.actions()[-1] == "login.throttled"
```

When the throttle refuses with 42 seconds, `LoginThrottledError` carries 42, no password check or dummy check happened and the last audit row is `login.throttled`.

```python
def test_a_hash_with_old_parameters_is_upgraded_at_sign_in(parts):
    users, hasher, _, _, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    hasher.rehash_wanted = True
    service.authenticate("alice", PASSWORD, "10.0.0.1")
    assert users.by_username("alice").password_hash == hasher.hash(PASSWORD)
```

When the hasher says the hash is outdated, a good sign-in stores a new hash.

```python
def test_get_user_returns_the_registered_user(parts):
    *_, service = parts
    user = service.register("alice", PASSWORD, "10.0.0.1")
    assert service.get_user(user.id) == user
    assert service.get_user(999) is None
```

`get_user` returns the user by id and `None` for an unknown id.

### Line by line: `tests/unit/test_sessions.py`

```python
from dataclasses import replace

import pytest

from notes_app.application.sessions import SessionPolicy, SessionService, hash_token
from tests.fakes import CountingTokens, FakeClock, InMemorySessions
```

Imports: `replace` (copy a frozen record with a change), `pytest`, the service, policy and `hash_token`, and the fakes.

```python
POLICY = SessionPolicy(idle_seconds=1800, absolute_seconds=28800, anonymous_seconds=900)
```

The policy is 30 minutes idle, 8 hours absolute and 15 minutes anonymous.

```python
@pytest.fixture
def parts():
    sessions, clock = InMemorySessions(), FakeClock()
    return sessions, clock, SessionService(sessions, CountingTokens(), clock, POLICY)
```

The `parts` fixture returns the in-memory sessions, the clock and a service that uses counting tokens.

```python
def test_only_the_hash_of_the_cookie_value_is_stored(parts):
    sessions, _, service = parts
    issued = service.start_anonymous()
    assert issued.raw_token not in sessions.rows
    assert hash_token(issued.raw_token) in sessions.rows
    assert issued.session.user_id is None
```

After `start_anonymous`, the raw token is not a key in the store but its hash is, and the user id is `None`: only the hash is stored.

```python
def test_an_anonymous_session_expires_quickly_and_a_signed_in_one_lasts_longer(parts):
    _, _, service = parts
    anonymous = service.start_anonymous()
    signed_in = service.sign_in(None, user_id=7)
    assert anonymous.max_age_seconds == 900
    assert signed_in.max_age_seconds == 28800
```

The anonymous session lives 900 seconds and the signed-in one 28,800.

```python
def test_signing_in_replaces_the_previous_session_and_its_csrf_token(parts):
    sessions, _, service = parts
    anonymous = service.start_anonymous()
    signed_in = service.sign_in(anonymous.raw_token, user_id=7)
    assert signed_in.raw_token != anonymous.raw_token
    assert service.resolve(anonymous.raw_token) is None  # the pre-login value no longer works
    assert signed_in.session.csrf_token != anonymous.session.csrf_token
    assert len(sessions.rows) == 1
```

Signing in with the anonymous cookie gives a different raw token and a different CSRF token, the old cookie no longer resolves, and only one session remains.

```python
def test_resolve_returns_the_session_until_it_has_been_idle_too_long(parts):
    _, clock, service = parts
    issued = service.sign_in(None, user_id=7)
    clock.advance(minutes=29)
    assert service.resolve(issued.raw_token) is not None
    clock.advance(minutes=31)
    assert service.resolve(issued.raw_token) is None
```

After 29 idle minutes the session resolves; 31 minutes later (60 in total, over the 30-minute limit) it does not.

```python
def test_activity_keeps_a_session_alive_past_the_idle_limit_but_not_the_absolute_limit(parts):
    _, clock, service = parts
    issued = service.sign_in(None, user_id=7)
    for _ in range(16):  # every 29 minutes, for 7 hours and 44 minutes
        clock.advance(minutes=29)
        assert service.resolve(issued.raw_token) is not None
    clock.advance(minutes=29)  # past 8 hours
    assert service.resolve(issued.raw_token) is None
```

Sixteen activities 29 minutes apart (7 hours 44 minutes) keep the session alive each time; the next one, past 8 hours, finds it dead: activity extends the idle limit but never the absolute limit.

```python
def test_an_expired_session_is_deleted_when_it_is_found(parts):
    sessions, clock, service = parts
    issued = service.sign_in(None, user_id=7)
    clock.advance(hours=9)
    assert service.resolve(issued.raw_token) is None
    assert sessions.rows == {}
```

After 9 hours, `resolve` returns `None` and also deletes the row.

```python
def test_unknown_or_missing_cookie_values_resolve_to_nothing(parts):
    *_, service = parts
    assert service.resolve(None) is None
    assert service.resolve("") is None
    assert service.resolve("never-issued") is None
```

`None`, an empty value and a never-issued value all resolve to nothing.

```python
def test_last_seen_is_written_at_most_once_a_minute(parts):
    sessions, clock, service = parts
    issued = service.sign_in(None, user_id=7)
    clock.advance(seconds=30)
    service.resolve(issued.raw_token)
    assert sessions.rows[hash_token(issued.raw_token)].last_seen_at != clock.now()
    clock.advance(seconds=31)
    service.resolve(issued.raw_token)
    assert sessions.rows[hash_token(issued.raw_token)].last_seen_at == clock.now()
```

After 30 seconds the stored last-seen time is not updated; after another 31 seconds (over a minute since the last write) it is: at most one write a minute.

```python
def test_sign_out_removes_the_session(parts):
    _, _, service = parts
    issued = service.sign_in(None, user_id=7)
    service.sign_out(issued.raw_token)
    service.sign_out(None)
    assert service.resolve(issued.raw_token) is None
```

`sign_out` removes the session; `sign_out(None)` does nothing and does not fail.

```python
def test_sign_in_purges_sessions_past_their_expiry(parts):
    sessions, clock, service = parts
    stale = service.start_anonymous()
    clock.advance(hours=1)
    service.sign_in(None, user_id=7)
    assert hash_token(stale.raw_token) not in sessions.rows
```

An anonymous session that is an hour old is past its 15 minutes; signing in purges it.

```python
def test_csrf_token_comparison(parts):
    _, _, service = parts
    session = service.start_anonymous().session
    assert service.csrf_valid(session, session.csrf_token)
    assert not service.csrf_valid(session, "wrong")
    assert not service.csrf_valid(session, None)
    assert not service.csrf_valid(replace(session, csrf_token="a"), "b")
```

The right CSRF token is valid; a wrong one, `None` and a mismatch between two different sessions' tokens are not.

### Line by line: `tests/unit/test_notes_service.py`

```python
import pytest

from notes_app.application.notes import NoteService
from notes_app.application.policy import OwnerOrSharedPolicy
from notes_app.domain.errors import InvalidInputError, NoteForbiddenError, NoteNotFoundError
from notes_app.domain.models import NoteRole
from tests.fakes import FakeClock, InMemoryNotes, InMemoryUsers, ListAudit
```

Imports of `pytest`, the service, the production policy, three errors, the role enumeration and the in-memory fakes.

```python
ALICE, BOB, CAROL = 1, 2, 3
```

`ALICE, BOB, CAROL = 1, 2, 3` names the user ids the in-memory store will assign (it numbers users from 1 in the order they are added).

```python
@pytest.fixture
def parts():
    users = InMemoryUsers()
    for name in ("alice", "bob", "carol"):
        users.add(name, "!")
    notes, audit = InMemoryNotes(users, FakeClock()), ListAudit()
    return notes, audit, NoteService(notes, users, OwnerOrSharedPolicy(), audit)
```

The `parts` fixture adds three users with the locked hash `!`, builds the in-memory notes and audit log, and a `NoteService` with the real production policy. The test therefore exercises the real authorization rule with fake storage.

```python
def test_owner_creates_reads_updates_and_deletes_a_note(parts):
    notes, audit, service = parts
    note = service.create(ALICE, " Plan ", "details")
    assert service.get(ALICE, note.id, "ip").title == "Plan"
    updated = service.update(ALICE, note.id, None, "new details", "ip")
    assert (updated.title, updated.content) == ("Plan", "new details")
    service.delete(ALICE, note.id, "ip")
    assert notes.get(note.id) is None
    assert audit.actions() == ["note.deleted"]
```

The owner creates a note (the title is trimmed to `Plan`), reads it, updates only the content (`None` for the title keeps it), deletes it, and the store no longer has it. The only audit row is `note.deleted`.

```python
@pytest.mark.parametrize("action", ["get", "update", "delete", "share"])
def test_a_stranger_gets_not_found_for_every_action_and_the_attempt_is_audited(parts, action):
    _, audit, service = parts
    note = service.create(ALICE, "Private", "secret")
    calls = {
        "get": lambda: service.get(BOB, note.id, "ip"),
        "update": lambda: service.update(BOB, note.id, "x", "y", "ip"),
        "delete": lambda: service.delete(BOB, note.id, "ip"),
        "share": lambda: service.share(BOB, note.id, "carol", "ip"),
    }
    with pytest.raises(NoteNotFoundError):
        calls[action]()
    assert audit.actions() == ["note.access_denied"]
    assert dict(audit.events[0].detail) == {"note_id": str(note.id), "reason": "no_access"}
```

`parametrize` runs the test for four actions: get, update, delete and share. A dictionary of small functions (`lambda`) maps each action to a call made by Bob on Alice's private note. Each must raise `NoteNotFoundError`, exactly one `note.access_denied` row must be written, and its detail must be the note id and the reason `no_access`.

```python
def test_a_missing_note_and_a_foreign_note_raise_the_same_error(parts):
    _, _, service = parts
    note = service.create(ALICE, "Private", "secret")
    with pytest.raises(NoteNotFoundError) as foreign:
        service.get(BOB, note.id, "ip")
    with pytest.raises(NoteNotFoundError) as missing:
        service.get(BOB, 999, "ip")
    assert type(foreign.value) is type(missing.value)
```

Bob asking for Alice's note and for note 999 both raise `NoteNotFoundError` of the same type, so a response cannot reveal whether an id exists.

```python
def test_a_reader_can_read_but_gets_forbidden_for_update_delete_and_share(parts):
    _, audit, service = parts
    note = service.create(ALICE, "Shared", "hello")
    service.share(ALICE, note.id, "bob", "ip")
    assert service.get(BOB, note.id, "ip").content == "hello"
    for call in (
        lambda: service.update(BOB, note.id, "x", None, "ip"),
        lambda: service.delete(BOB, note.id, "ip"),
        lambda: service.share(BOB, note.id, "carol", "ip"),
    ):
        with pytest.raises(NoteForbiddenError):
            call()
    assert audit.actions().count("note.access_denied") == 3
    assert dict(audit.events[-1].detail)["reason"] == "read_only"
```

Alice shares a note with Bob. Bob can read it. For update, delete and share, Bob gets `NoteForbiddenError` (a reader may see but not change). Three denials are audited, and the last has the reason `read_only`.

```python
def test_sharing_with_yourself_or_an_unknown_user_is_refused(parts):
    *_, service = parts
    note = service.create(ALICE, "Plan", "x")
    for username in ("alice", "nobody"):
        with pytest.raises(InvalidInputError):
            service.share(ALICE, note.id, username, "ip")
```

Sharing with yourself (`alice`) or with an unknown user raises `InvalidInputError`.

```python
def test_listing_shows_owned_and_shared_notes_with_the_role(parts):
    *_, service = parts
    own = service.create(BOB, "Mine", "x")
    other = service.create(ALICE, "Theirs", "y")
    service.create(CAROL, "Hidden", "z")
    service.share(ALICE, other.id, "bob", "ip")
    visible = {item.note.id: item.role for item in service.list_visible(BOB)}
    assert visible == {own.id: NoteRole.OWNER, other.id: NoteRole.READER}
```

Bob owns one note, Alice owns one shared with Bob, Carol owns one shared with nobody. Bob's list is a dictionary of note id to role: his own is `OWNER`, Alice's is `READER`, Carol's is absent.

```python
def test_update_validates_the_new_values(parts):
    *_, service = parts
    note = service.create(ALICE, "Plan", "x")
    with pytest.raises(InvalidInputError):
        service.update(ALICE, note.id, "", None, "ip")
    with pytest.raises(InvalidInputError):
        service.update(ALICE, note.id, None, "a\x00b", "ip")
```

`update` validates the new values: an empty title and a content with a NUL character are refused.

### Line by line: `tests/unit/test_security_headers.py`

```python
from flask import Response

from notes_app.interfaces.http.security import (
    CONTENT_SECURITY_POLICY,
    HARDENED_COOKIE,
    SESSION_COOKIE,
    apply_security_headers,
    clear_session_cookie,
    set_session_cookie,
)
```

Imports: Flask's `Response` and the security helpers.

```python
def test_the_content_security_policy_allows_no_script_and_no_framing():
    directives = dict(part.strip().split(" ", 1) for part in CONTENT_SECURITY_POLICY.split(";"))
    assert directives["default-src"] == "'none'"
    assert "script-src" not in directives  # falls back to default-src 'none'
    assert directives["frame-ancestors"] == "'none'"
    assert directives["base-uri"] == "'none'"
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY
```

The CSP text is split on `;` into directives, each directive into name and value (`split(" ", 1)`), and put in a dictionary. `default-src` is `'none'`, there is no `script-src` (so scripts fall back to the `'none'` default and none can run), `frame-ancestors` and `base-uri` are `'none'`, and neither `unsafe-inline` nor `unsafe-eval` appears.

```python
def test_headers_are_added_but_a_handlers_own_value_wins():
    response = Response("x")
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    apply_security_headers(response)
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
```

A response that already has `X-Frame-Options: SAMEORIGIN` keeps it after `apply_security_headers`, while the missing headers are added: a handler's own value wins.

```python
def test_the_session_cookie_is_host_prefixed_http_only_secure_and_same_site():
    response = Response("x")
    set_session_cookie(response, "opaque", 900, HARDENED_COOKIE)
    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=opaque")
    for attribute in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/", "Max-Age=900"):
        assert attribute in cookie
    assert "Domain" not in cookie
```

`set_session_cookie` produces a `Set-Cookie` header that starts with `__Host-session=opaque` and contains `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/` and `Max-Age=900`, with no `Domain` (which the `__Host-` prefix forbids).

```python
def test_clearing_the_cookie_expires_it_with_the_same_attributes():
    response = Response("x")
    clear_session_cookie(response, HARDENED_COOKIE)
    cookie = response.headers["Set-Cookie"]
    assert "Max-Age=0" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
```

`clear_session_cookie` expires the cookie with `Max-Age=0` and the same `Secure` and `HttpOnly` attributes.

### Line by line: `tests/unit/test_threat_model_document.py`

```python
"""The threat model cannot drift from the suite: every fixed threat links a test that exists."""
```

The docstring: the threat model cannot drift from the test suite, because every fixed threat must link a test that exists.

```python
import re
from itertools import takewhile
from pathlib import Path
```

Imports: `re`, `takewhile` (takes items from an iterator while a condition holds) and `Path`.

```python
ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = (ROOT / "docs" / "THREAT_MODEL.md").read_text()
TEST_REFERENCE = re.compile(r"`(tests/[\w/]+\.py)::(\w+)`")
```

`ROOT` is the repository; `DOCUMENT` is the text of `docs/THREAT_MODEL.md`. `TEST_REFERENCE` is a regular expression that finds a reference of the form `` `tests/path/file.py::test_name` `` and captures the path and the name.

```python
def _table_rows(heading: str) -> list[list[str]]:
    """The body rows of the first table under a heading."""
    lines = iter(DOCUMENT.split(heading, 1)[1].splitlines())
    table = []
    for line in lines:
        if line.startswith("|"):
            table.append(line)
            table.extend(takewhile(lambda row: row.startswith("|"), lines))
            break
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in table]
    return rows[2:]  # drop the header and its separator
```

`_table_rows` finds the first Markdown table after a heading. It splits the document at the heading, walks the following lines and, at the first line starting with `|`, collects that line and all following lines that start with `|`. Each line is split on `|` into trimmed cells. `rows[2:]` drops the header row and the separator row.

```python
def test_every_boundary_has_at_least_one_threat():
    boundaries = {row[1] for row in _table_rows("## Verification note")}
    assert boundaries == {"B1", "B2", "B3"}
```

The set of boundary cells (second column) in the threat table must be exactly `B1`, `B2` and `B3`: every trust boundary has at least one threat.

```python
def test_every_fixed_threat_links_a_test_that_exists():
    rows = _table_rows("## Verification note")
    assert len(rows) >= 20
    for threat_id, _boundary, _stride, _threat, control, proof, status in rows:
        assert status == "fixed", threat_id
        assert control, threat_id
        references = TEST_REFERENCE.findall(proof)
        assert references, f"{threat_id} names no test"
        for path, name in references:
            source = (ROOT / path).read_text()
            assert re.search(rf"^def {name}\(", source, re.MULTILINE), f"{threat_id}: {path}::{name} does not exist"
```

The table must have at least 20 rows. For every row (the columns are id, boundary, STRIDE letter, threat, control, proof, status): the status is `fixed`, the control text is not empty, the proof cell names at least one test, and for every named test the file exists and contains a line `def <name>(`. A threat cannot claim a proof that does not exist.

```python
def test_threat_ids_are_unique_and_sequential():
    ids = [row[0] for row in _table_rows("## Verification note")]
    assert ids == [f"T{number}" for number in range(1, len(ids) + 1)]
```

The ids are `T1`, `T2`, ... in order with no gaps.

```python
def test_at_least_one_threat_is_accepted_with_a_reason():
    accepted = _table_rows("## Accepted risks")
    assert accepted
    assert all(len(row[2]) > 40 for row in accepted)
    assert accepted[0][0] == "A1"
```

The accepted-risks table is not empty, every reason is longer than 40 characters, and the first id is `A1`: accepting a risk needs a written reason.

### Line by line: `tests/unit/test_http_app.py`

```python
"""The HTTP layer over in-memory fakes: routing, content negotiation, error mapping and cookie handling."""
```

The docstring: the HTTP layer over in-memory fakes, covering routing, content negotiation, error mapping and cookie handling.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import pytest
from flask import Flask
```

`pytest` and Flask's `Flask` type.

```python
from notes_app.application.accounts import AccountService
from notes_app.application.notes import NoteService
from notes_app.application.policy import OwnerOrSharedPolicy
from notes_app.application.sessions import SessionPolicy, SessionService
from notes_app.infrastructure.settings import Settings
from notes_app.interfaces.composition import Container
from notes_app.interfaces.http.app import create_app
from notes_app.interfaces.http.security import SESSION_COOKIE
```

Imports of the services, the production access policy, the session policy, the settings, the container, the application factory and the cookie name.

```python
from tests.fakes import (
    CountingTokens,
    FakeClock,
    InMemoryNotes,
    InMemorySessions,
    InMemoryThrottle,
    InMemoryUsers,
    ListAudit,
    ReversibleHasher,
)
from tests.support import HOSTILE, Browser, new_password, new_username
```

Imports of every fake and of the helpers (`HOSTILE` attack text, the `Browser` client and the generators of passwords and names).

```python
class FakeDatabase:
    def __init__(self) -> None:
        self.healthy = True

    def ping(self) -> bool:
        return self.healthy

    def close(self) -> None:
        pass
```

`FakeDatabase` has `healthy` (true at first), `ping()` and a `close()` that does nothing, so tests can make the "database" go down.

```python
@pytest.fixture
def parts():
    clock, users, audit = FakeClock(), InMemoryUsers(), ListAudit()
    settings = Settings.from_environment({"NOTES_DB_PASSWORD": "x", "APP_ENV": "test"})
    database = FakeDatabase()
    container = Container(
        settings=settings,
        database=database,  # type: ignore[arg-type]
        audit=audit,
        accounts=AccountService(
            users, ReversibleHasher(), InMemoryThrottle(max_failures=3, window_seconds=600), audit, clock
        ),
        sessions=SessionService(
            InMemorySessions(),
            CountingTokens(),
            clock,
            SessionPolicy(idle_seconds=1800, absolute_seconds=28800, anonymous_seconds=900),
        ),
        notes=NoteService(InMemoryNotes(users, clock), users, OwnerOrSharedPolicy(), audit),
    )
    return create_app(container), database, audit
```

The `parts` fixture builds a full container out of fakes: settings in `test` mode, the fake database, the audit list, an account service with a real in-memory throttle (3 failures in 600 seconds), a session service with the usual lifetimes and a note service with the real policy. `# type: ignore[arg-type]` tells the type checker to accept the fake where a real `Database` is expected. It returns the Flask app, the database and the audit list.

```python
@pytest.fixture
def app(parts) -> Flask:
    flask_app: Flask = parts[0]
    return flask_app
```

The `app` fixture picks the app out of `parts`.

```python
def test_health_endpoints(parts):
    app, database, _ = parts
    browser = Browser(app)
    assert browser.get("/healthz").get_json() == {"status": "ok"}
    assert browser.get("/readyz").status_code == 200
    database.healthy = False
    response = browser.get("/readyz")
    assert response.status_code == 503
    assert "Strict-Transport-Security" in response.headers
```

Health: `/healthz` returns `{"status": "ok"}`, `/readyz` returns 200; after the fake goes unhealthy `/readyz` returns 503, and even that response carries the `Strict-Transport-Security` header (headers are added to every response).

```python
def test_sign_up_sign_in_and_the_notes_page(app):
    browser = Browser(app)
    username, _ = browser.register()
    page = browser.get("/notes")
    assert page.status_code == 200
    assert f"Signed in as {username}" in page.get_data(as_text=True)
    assert browser.get("/", follow_redirects=False).headers["Location"] == "/notes"
```

A new user signs up and signs in; `/notes` returns 200 and shows "Signed in as <name>"; `/` redirects to `/notes`.

```python
def test_an_anonymous_visitor_is_sent_to_sign_in_by_page_and_refused_by_api(app):
    browser = Browser(app)
    page = browser.get("/notes")
    assert (page.status_code, page.headers["Location"]) == (303, "/login")
    api = browser.get("/notes", headers={"Accept": "application/json"})
    assert api.status_code == 401
    assert api.get_json()["error"] == "unauthenticated"
    assert browser.get("/", follow_redirects=False).headers["Location"] == "/login"
```

A visitor with no session asking for the page `/notes` gets 303 to `/login`; asking with `Accept: application/json` gets 401 and the error code `unauthenticated`; `/` redirects to `/login`.

```python
def test_sign_up_reports_a_taken_username_and_a_weak_password_without_leaking_more(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    assert browser.sign_up(username, password).status_code == 303
    taken = browser.sign_up(username, password)
    assert taken.status_code == 400
    assert "not available" in taken.get_data(as_text=True)
    short = browser.sign_up(new_username(), "short")
    assert short.status_code == 400
    assert "12 to 128" in short.get_data(as_text=True)
    assert browser.get("/signup").status_code == 200
```

Signing up twice with the same name gives 400 and a message saying "not available" (no more detail); a 5-character password gives 400 and a message with "12 to 128"; the sign-up page itself answers 200.

```python
def test_wrong_password_and_unknown_user_give_the_same_response(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    wrong = browser.sign_in(username, "not the password at all")
    unknown = browser.sign_in(new_username(), password)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_data() == unknown.get_data() or "Invalid username or password." in unknown.get_data(as_text=True)
```

A wrong password and an unknown user both give 401. The last assertion compares the two bodies, or accepts the unknown-user page if it contains the fixed message "Invalid username or password.".

```python
def test_the_fourth_failed_sign_in_is_throttled_with_retry_after(app):
    browser = Browser(app)
    username = new_username()
    browser.sign_up(username, new_password())
    statuses = [browser.sign_in(username, "wrong password number").status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
    throttled = browser.sign_in(username, "wrong password number")
    assert int(throttled.headers["Retry-After"]) > 0
```

With a limit of 3, four failed sign-ins give 401, 401, 401 and then 429; the next attempt's `Retry-After` header is a positive number.

```python
def test_sign_out_clears_the_cookie_and_the_server_side_session(app, parts):
    browser = Browser(app)
    browser.register()
    old_cookie = browser.session_cookie()
    response = browser.post("/logout", data={"csrf_token": browser.csrf_token()})
    assert response.status_code == 303
    assert f"{SESSION_COOKIE}=;" in response.headers["Set-Cookie"]
    stale = Browser(app)
    stale.client.set_cookie(SESSION_COOKIE, old_cookie or "", domain="localhost")
    assert stale.get("/notes").status_code == 303
```

After sign-out the `Set-Cookie` header clears the cookie (`__Host-session=;`). A second browser given the old cookie value by hand is sent to the login page (303), so the session is dead on the server.

```python
def test_a_post_without_a_session_or_token_is_refused_and_audited(app, parts):
    *_, audit = parts
    response = Browser(app).post("/login", data={"username": "a", "password": "b"})
    assert response.status_code == 403
    assert audit.actions() == ["csrf.rejected"]
```

A POST to `/login` with no session and no CSRF token gets 403, and the only audit row is `csrf.rejected`.

```python
def test_notes_through_the_json_api_and_the_pages(app):
    browser = Browser(app)
    browser.register()
    note_id = browser.create_note("Plan", "details")
    assert browser.api("GET", f"/notes/{note_id}", csrf=None).get_json()["content"] == "details"
    patched = browser.api("PATCH", f"/notes/{note_id}", json={"content": "changed"})
    assert patched.get_json()["content"] == "changed"
    listing = browser.get("/notes", headers={"Accept": "application/json"}).get_json()
    assert listing["notes"] == [{"id": note_id, "title": "Plan", "role": "owner"}]
    assert "Plan" in browser.get(f"/notes/{note_id}").get_data(as_text=True)
    assert browser.api("DELETE", f"/notes/{note_id}").status_code == 204
    assert browser.api("GET", f"/notes/{note_id}", csrf=None).status_code == 404
```

JSON API round trip: create a note; read it (GET needs no CSRF token); patch the content; the list is JSON with the note's id, title and role `owner`; the HTML page shows the title; delete answers 204; reading it again answers 404.

```python
def test_the_form_flow_creates_a_note_and_redirects_to_it(app):
    browser = Browser(app)
    browser.register()
    response = browser.post(
        "/notes", data={"title": "From a form", "content": HOSTILE, "csrf_token": browser.csrf_token()}
    )
    assert response.status_code == 303
    page = browser.get(response.headers["Location"]).get_data(as_text=True)
    assert "&lt;script&gt;" in page
    assert "<script>" not in page
    invalid = browser.post("/notes", data={"title": "", "content": "x", "csrf_token": browser.csrf_token()})
    assert invalid.status_code == 400
    assert "1 to 120" in invalid.get_data(as_text=True)
    assert browser.api("POST", "/notes", json={"title": "", "content": "x"}).status_code == 400
    assert browser.api("POST", "/notes", json=["not", "an", "object"]).status_code == 400
```

Form flow: a form post creates a note with the hostile content and redirects (303); the page shows `&lt;script&gt;` and no real `<script>`; an empty title gives 400 with a message containing "1 to 120"; the JSON API with an empty title and with a body that is a list instead of an object both give 400.

```python
def test_sharing_gives_a_second_user_read_only_access(app):
    owner, reader = Browser(app), Browser(app)
    owner.register()
    reader_name, _ = reader.register()
    note_id = owner.create_note("Shared", "hello")
    assert reader.api("GET", f"/notes/{note_id}", csrf=None).status_code == 404
    page_share = owner.post(
        f"/notes/{note_id}/shares", data={"username": reader_name, "csrf_token": owner.csrf_token()}
    )
    assert page_share.status_code == 303
    assert reader.api("GET", f"/notes/{note_id}", csrf=None).get_json()["content"] == "hello"
    assert reader.api("PATCH", f"/notes/{note_id}", json={"content": "x"}).status_code == 403
    bad = owner.post(f"/notes/{note_id}/shares", data={"username": "nobody_here", "csrf_token": owner.csrf_token()})
    assert bad.status_code == 400
    assert owner.api("POST", f"/notes/{note_id}/shares", json={"username": "nobody_here"}).status_code == 400
    assert owner.api("POST", f"/notes/{note_id}/shares", json={"username": reader_name}).status_code == 204
```

Sharing: the reader cannot see the note (404); the owner shares by form (303); the reader can read the content; the reader cannot patch (403); sharing with an unknown user gives 400 by form and by JSON; sharing with the reader by JSON gives 204.

```python
def test_unknown_routes_and_methods_use_the_same_error_shape(app):
    browser = Browser(app)
    assert browser.get("/nope").status_code == 404
    missing = browser.get("/nope", headers={"Accept": "application/json"})
    assert missing.status_code == 404
    assert missing.get_json()["error"] == "not_found"
    assert browser.get("/logout").status_code == 405
```

An unknown path gives 404 as HTML and as JSON with the code `not_found`; a GET to `/logout` (a POST-only route) gives 405.

```python
def test_an_unexpected_error_returns_no_internal_detail(parts):
    app, *_ = parts

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    response = Browser(app).get("/boom", headers={"Accept": "application/json"})
    assert response.status_code == 500
    assert "secret internal detail" not in response.get_data(as_text=True)
    assert response.get_json()["error"] == "internal_error"
```

The test adds a route `/boom` that raises an error with the text `secret internal detail`. The answer is 500, the text is nowhere in the body and the error code is `internal_error`.

```python
def test_an_oversized_body_is_refused(app):
    browser = Browser(app)
    browser.register()
    response = browser.api("POST", "/notes", json={"title": "x", "content": "y" * 70_000})
    assert response.status_code == 413
```

A JSON body of 70,000 characters is over the 64 KiB limit and gets 413.

### Line by line: `tests/security/test_authentication.py`

These tests need the real database (`make up`) and carry the marker `security`.

```python
"""Stretch: throttling of sign-in attempts, and no hint about which half of a credential was wrong."""
```

The docstring: throttling of sign-in attempts and no hint about which half of a credential was wrong.

```python
import pytest

from tests.support import Browser, new_password, new_username
```

Imports of `pytest` and the helpers.

```python
pytestmark = pytest.mark.security
```

`pytestmark = pytest.mark.security` puts the label on every test in the file.

```python
def test_repeated_failures_are_throttled_with_retry_after_and_audited(app, owner_sql, settings):
    browser = Browser(app)
    username = new_username()
    browser.sign_up(username, new_password())
    statuses = [
        browser.sign_in(username, "a wrong password again").status_code for _ in range(settings.login_max_failures)
    ]
    assert statuses == [401] * settings.login_max_failures

    throttled = browser.sign_in(username, "a wrong password again")
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) > 0
    assert owner_sql("SELECT count(*) FROM audit_events WHERE action = 'login.throttled'") == [(1,)]
```

The `app`, `owner_sql` and `settings` fixtures come from `conftest.py`. After signing up, the configured number of wrong sign-ins each give 401; the next gives 429 with a positive `Retry-After`; and the owner's view of the database shows exactly one `login.throttled` audit row.

```python
def test_a_correct_password_is_also_refused_while_throttled(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    for _ in range(5):
        browser.sign_in(username, "a wrong password again")
    assert browser.sign_in(username, password).status_code == 429
```

After five failures, even the correct password gets 429: while throttled, a guess is not tested at all.

```python
def test_a_different_client_address_is_not_throttled_by_someone_elses_failures(app):
    username, password = new_username(), new_password()
    attacker, owner = Browser(app, remote_addr="203.0.113.9"), Browser(app, remote_addr="198.51.100.4")
    owner.sign_up(username, password)
    for _ in range(6):
        attacker.sign_in(username, "a wrong password again")
    assert owner.sign_in(username, password).status_code == 303
```

The attacker's browser has address `203.0.113.9` and the owner's `198.51.100.4` (addresses reserved for documentation). Six failures from the attacker do not stop the owner from signing in (303), because the key includes the address.

```python
def test_the_throttle_stores_neither_the_username_nor_the_address(app, owner_sql):
    browser = Browser(app, remote_addr="203.0.113.77")
    username = new_username("probe")
    browser.sign_in(username, "a wrong password again")
    rows = owner_sql("SELECT key_hash FROM login_failures")
    assert len(rows) == 1
    assert username not in rows[0][0]
    assert "203.0.113.77" not in rows[0][0]
```

After one failed attempt from `203.0.113.77` for a probe username, the table `login_failures` has one row whose key hash contains neither the username nor the address.

```python
def test_unknown_user_and_wrong_password_look_identical(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    wrong = browser.sign_in(username, "definitely the wrong one")
    unknown = browser.sign_in(new_username("nobody"), password)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_data() == unknown.get_data().replace(
        b"", b""
    ) or "Invalid username or password." in unknown.get_data(as_text=True)
    assert "Invalid username or password." in wrong.get_data(as_text=True)
```

An unknown user and a wrong password both give 401 with the same fixed message in the page (the odd-looking comparison accepts either identical bodies or the fixed message), and the wrong-password page contains "Invalid username or password.".

### Line by line: `tests/security/test_passwords.py`

```python
"""Step 2: passwords are stored as salted slow hashes and never logged."""
```

The docstring: step 2, passwords are stored as salted slow hashes and never logged.

```python
import pytest

from tests.support import Browser, new_password, new_username

pytestmark = pytest.mark.security
```

Imports and the `security` marker.

```python
def _hashes(owner_sql, *usernames):
    rows = owner_sql("SELECT username, password_hash FROM users WHERE username = ANY(%s)", (list(usernames),))
    return dict(rows)
```

`_hashes` asks the database, as the owner, for the stored hashes of some usernames (`= ANY(%s)` matches any value in a list) and returns a dictionary from name to hash.

```python
def test_passwords_are_salted_and_not_logged(app, owner_sql, captured_logs):
    password = new_password()
    first, second = Browser(app), Browser(app)
    name_a, name_b = new_username("a"), new_username("b")
    assert first.sign_up(name_a, password).status_code == 303
    assert second.sign_up(name_b, password).status_code == 303
    assert first.sign_in(name_a, password).status_code == 303
    assert first.sign_in(name_a, "a different wrong password").status_code == 401
```

Two users sign up with the **same** password; one signs in correctly, then fails once with a different password. `captured_logs` records everything logged.

```python
    stored = _hashes(owner_sql, name_a, name_b)
    assert stored[name_a] != stored[name_b]  # same password, different hash: salted
    assert stored[name_a].startswith("$argon2id$")  # a real algorithm identifier, not a raw digest
    assert password not in stored[name_a]
    assert password not in captured_logs.getvalue()  # never appears in any log line
    assert "a different wrong password" not in captured_logs.getvalue()
```

The stored hashes of the two users differ (salted); they start with `$argon2id$` (a real algorithm identifier, not a raw digest); neither contains the password; and neither the password nor the wrong password appears anywhere in the log output. This is the test that `UNSAFE_WEAK_PASSWORD_HASH` must make fail.

```python
def test_the_login_response_and_pages_never_echo_the_password(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    response = browser.sign_in(username, "not the right password")
    assert "not the right password" not in response.get_data(as_text=True)
    assert response.status_code == 401
```

A failed sign-in returns 401 and the page does not echo the submitted password.

### Line by line: `tests/security/test_session.py`

```python
"""Step 5: session cookie flags, security headers and CSRF."""
```

The docstring: step 5, session cookie flags, security headers and CSRF.

```python
import re

import pytest

from notes_app.interfaces.http.security import SESSION_COOKIE
from tests.support import Browser, new_password, new_username
```

Imports: `re`, `pytest`, the cookie name and the helpers.

```python
pytestmark = pytest.mark.security
REQUIRED_HEADERS = {
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=",
}
```

The `security` marker. `REQUIRED_HEADERS` maps five header names to a text each response must contain: the CSP with `frame-ancestors 'none'`, `nosniff`, `DENY`, `no-referrer` and an HSTS header with `max-age=`.

```python
def _session_cookie_header(response):
    cookies = [value for value in response.headers.getlist("Set-Cookie") if value.startswith(SESSION_COOKIE)]
    assert len(cookies) == 1
    return cookies[0]
```

`_session_cookie_header` collects the `Set-Cookie` headers that begin with the session cookie's name and asserts there is exactly one, then returns it.

```python
def test_session_cookie_flags(app, owner_sql):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    cookie = _session_cookie_header(browser.sign_in(username, password))
    attributes = {part.strip().split("=")[0] for part in cookie.split(";")[1:]}
    assert {"HttpOnly", "Secure", "SameSite", "Path"} <= attributes
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie
    assert "Domain" not in cookie  # with the __Host- prefix, the browser enforces this too
```

The flags test: sign up, sign in, take the cookie header. The attribute names after the first `;` must include `HttpOnly`, `Secure`, `SameSite` and `Path` (`<=` between sets means "is a subset of"); `SameSite=Lax` and `Path=/` are in it; there is no `Domain`. This test is what `UNSAFE_WEAK_SESSION_COOKIE` must break.

```python
    value = cookie.split("=", 1)[1].split(";", 1)[0]
    assert len(value) >= 40  # 256 bits of randomness
    assert re.fullmatch(r"[\w-]+\.[\w-]+\.[\w-]+", value) is None  # opaque: not a JWT carrying claims
    assert owner_sql("SELECT count(*) FROM sessions WHERE token_hash = %s", (value,)) == [
        (0,)
    ]  # only its hash is stored
```

The cookie value is at least 40 characters (256 bits of randomness encode to 43), it does not look like a signed token of three dot-separated parts (opaque: no claims inside), and the database holds no row whose `token_hash` equals the raw value, so only its hash is stored.

```python
def test_security_headers_on_every_response(app):
    browser = Browser(app)
    browser.register()
    responses = [
        browser.get("/login"),
        browser.get("/notes"),
        browser.get("/no-such-page"),
        browser.api("GET", "/notes/999999", csrf=None),
        browser.get("/healthz"),
        browser.get("/static/style.css"),
    ]
    for response in responses:
        for header, expected in REQUIRED_HEADERS.items():
            assert expected in response.headers.get(header, ""), (header, response.status_code)
```

Six responses are collected: the login page, the notes page, an unknown page, a JSON 404 for a note, the health check and the stylesheet. Each must carry every required header, which shows headers are on every response, including errors and static files.

```python
def test_state_changing_request_without_csrf_token_is_refused(app, owner_sql):
    browser = Browser(app)
    browser.register()
    note_id = browser.create_note("Keep me", "x")

    assert browser.api("POST", "/notes", json={"title": "Forged", "content": "x"}, csrf=None).status_code == 403
    assert (
        browser.api("POST", "/notes", json={"title": "Forged", "content": "x"}, csrf="wrong-token").status_code == 403
    )
    assert browser.api("DELETE", f"/notes/{note_id}", csrf=None).status_code == 403
    assert browser.api("PATCH", f"/notes/{note_id}", json={"content": "forged"}, csrf=None).status_code == 403
    assert browser.post("/logout").status_code == 403
    assert owner_sql("SELECT title, content FROM notes") == [
        ("Keep me", "x")
    ]  # nothing was created, changed or deleted

    assert (
        browser.api("POST", "/notes", json={"title": "Real", "content": "x"}).status_code == 201
    )  # with the token it works
```

CSRF: after registering and creating a note, five state-changing requests without a valid token are all refused with 403: a create with no token, a create with a wrong token, a delete with no token, a patch with no token, and a logout post with no token. The database still has only the original note, untouched. With the real token the same create answers 201. This is the pair of tests `UNSAFE_SKIP_CSRF` must break.

```python
def test_another_sessions_csrf_token_does_not_work(app):
    victim, attacker = Browser(app), Browser(app)
    victim.register()
    attacker.register()
    assert (
        victim.api("POST", "/notes", json={"title": "x", "content": "y"}, csrf=attacker.csrf_token()).status_code == 403
    )
```

A token taken from the attacker's session does not work for the victim's session (403).

```python
def test_the_session_id_changes_at_sign_in(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    before = browser.session_cookie()
    assert before is not None
    browser.sign_in(username, password)
    after = browser.session_cookie()
    assert after is not None
    assert after != before
    planted = Browser(app)
    planted.client.set_cookie(SESSION_COOKIE, before, domain="localhost")
    assert planted.get("/notes", headers={"Accept": "application/json"}).status_code == 401
```

The session id changes at sign-in: the cookie before and after differ. A new browser given the pre-login cookie by hand gets 401, so a planted pre-login value is useless (defeats session fixation).

```python
def test_sign_out_ends_the_session_on_the_server(app, owner_sql):
    browser = Browser(app)
    browser.register()
    stolen = browser.session_cookie()
    assert browser.post("/logout", data={"csrf_token": browser.csrf_token()}).status_code == 303
    thief = Browser(app)
    thief.client.set_cookie(SESSION_COOKIE, stolen or "", domain="localhost")
    assert thief.get("/notes", headers={"Accept": "application/json"}).status_code == 401
    assert owner_sql("SELECT count(*) FROM sessions WHERE user_id IS NOT NULL") == [(0,)]
```

After sign-out a thief using the stolen cookie gets 401, and no signed-in session row remains.

```python
def test_a_session_past_its_expiry_is_refused(app, owner_sql):
    browser = Browser(app)
    browser.register()
    owner_sql("UPDATE sessions SET expires_at = now() - interval '1 second' WHERE user_id IS NOT NULL")
    assert browser.get("/notes", headers={"Accept": "application/json"}).status_code == 401
```

The test sets `expires_at` one second in the past in the database; the next request gets 401.

```python
def test_an_idle_session_is_refused(app, owner_sql):
    browser = Browser(app)
    browser.register()
    owner_sql("UPDATE sessions SET last_seen_at = now() - interval '2 hours' WHERE user_id IS NOT NULL")
    assert browser.get("/notes", headers={"Accept": "application/json"}).status_code == 401
```

The test sets `last_seen_at` two hours back, past the 30-minute idle limit; the next request gets 401.

```python
def test_an_unknown_or_malformed_cookie_value_is_refused(app):
    for value in ("never-issued", "a" * 3000, "../../etc/passwd", "' OR '1'='1"):
        browser = Browser(app)
        browser.client.set_cookie(SESSION_COOKIE, value, domain="localhost")
        assert browser.get("/notes", headers={"Accept": "application/json"}).status_code == 401
```

Four bad cookie values (never issued, 3,000 characters, a path-traversal text and a SQL text) each get 401 and none crashes anything.

### Line by line: `tests/security/test_authorization.py`

```python
"""Step 4: authorization is checked in the service for every note, on every request."""
```

The docstring: step 4, authorization is checked in the service for every note, on every request.

```python
import pytest

from tests.support import Browser

pytestmark = pytest.mark.security
```

Imports and the `security` marker.

```python
@pytest.fixture
def two_users(app):
    user_a, user_b = Browser(app), Browser(app)
    user_a.register("usera")
    user_b.register("userb")
    return user_a, user_b, user_b.create_note("B's private note", "only for B")
```

The `two_users` fixture registers user A and user B and has B create a private note; it returns both browsers and the note's id.

```python
def test_user_a_cannot_read_update_or_delete_user_b_note(two_users, owner_sql):
    client_a, _, user_b_note_id = two_users
    assert client_a.api("GET", f"/notes/{user_b_note_id}", csrf=None).status_code == 404
    assert client_a.api("PATCH", f"/notes/{user_b_note_id}", json={"content": "hacked"}).status_code == 404
    assert client_a.api("DELETE", f"/notes/{user_b_note_id}").status_code == 404
    assert owner_sql("SELECT content FROM notes WHERE id = %s", (user_b_note_id,)) == [("only for B",)]
```

A reads, patches and deletes B's note: each is 404, and the database still holds B's content. This is the main test `UNSAFE_SKIP_OWNERSHIP_CHECK` must break.

```python
def test_changing_the_id_in_the_url_reaches_no_note_of_another_user(two_users):
    client_a, _, user_b_note_id = two_users
    own_id = client_a.create_note("A's own note", "mine")
    reachable = [
        note_id
        for note_id in range(1, user_b_note_id + 5)
        if client_a.api("GET", f"/notes/{note_id}", csrf=None).status_code == 200
    ]
    assert reachable == [own_id]
```

A creates a note of their own, then tries every id from 1 up to B's id plus 4. The list of ids that answer 200 must be exactly A's own note: walking ids reaches no foreign note.

```python
def test_a_foreign_note_and_a_missing_note_are_indistinguishable(two_users):
    client_a, _, user_b_note_id = two_users
    foreign = client_a.api("GET", f"/notes/{user_b_note_id}", csrf=None)
    missing = client_a.api("GET", "/notes/999999", csrf=None)
    assert (foreign.status_code, foreign.get_json()) == (missing.status_code, missing.get_json())
```

A foreign note and a missing note give the same status and the same JSON body, so an attacker learns nothing about which ids exist.

```python
def test_the_owner_in_the_request_body_is_ignored(two_users, owner_sql):
    client_a, _, _ = two_users
    owner_b = owner_sql("SELECT id FROM users ORDER BY id DESC LIMIT 1")[0][0]
    note_id = client_a.api("POST", "/notes", json={"title": "x", "content": "y", "owner_id": owner_b}).get_json()["id"]
    owner_a = owner_sql("SELECT owner_id FROM notes WHERE id = %s", (note_id,))[0][0]
    assert owner_a != owner_b
```

A tries to create a note while claiming `owner_id` of B in the body. The stored owner is not B: the owner always comes from the session, never from the request.

```python
def test_every_notes_route_refuses_a_request_with_no_session(app):
    anonymous = Browser(app)
    token = anonymous.csrf_token()
    headers = {"Accept": "application/json", "X-CSRF-Token": token}
    for method, path in (
        ("GET", "/notes"),
        ("POST", "/notes"),
        ("GET", "/notes/1"),
        ("PATCH", "/notes/1"),
        ("DELETE", "/notes/1"),
        ("POST", "/notes/1/shares"),
    ):
        assert anonymous.request(method, path, headers=headers, json={}).status_code == 401, (method, path)
```

A visitor with only an anonymous session and a valid CSRF token tries six routes (list, create, read, patch, delete, share) and each answers 401.

```python
def test_a_user_the_note_is_shared_with_can_read_but_not_change_or_share_it(app, owner_sql):
    owner, reader = Browser(app), Browser(app)
    owner.register("owner")
    reader_name, _ = reader.register("reader")
    note_id = owner.create_note("Shared", "for the reader")
    assert owner.api("POST", f"/notes/{note_id}/shares", json={"username": reader_name}).status_code == 204

    assert reader.api("GET", f"/notes/{note_id}", csrf=None).get_json()["content"] == "for the reader"
    assert reader.api("PATCH", f"/notes/{note_id}", json={"content": "x"}).status_code == 403
    assert reader.api("DELETE", f"/notes/{note_id}").status_code == 403
    assert reader.api("POST", f"/notes/{note_id}/shares", json={"username": reader_name}).status_code == 403
    assert owner_sql("SELECT content FROM notes WHERE id = %s", (note_id,)) == [("for the reader",)]
```

The owner shares a note; the reader can read it, but patch, delete and share give 403 and the content in the database is unchanged.

```python
def test_revoking_access_takes_effect_on_the_next_request(app, owner_sql):
    owner, reader = Browser(app), Browser(app)
    owner.register("owner")
    reader_name, _ = reader.register("reader")
    note_id = owner.create_note("Shared", "x")
    owner.api("POST", f"/notes/{note_id}/shares", json={"username": reader_name})
    assert reader.api("GET", f"/notes/{note_id}", csrf=None).status_code == 200
    owner_sql("DELETE FROM note_shares WHERE note_id = %s", (note_id,))
    assert reader.api("GET", f"/notes/{note_id}", csrf=None).status_code == 404  # looked up fresh every time
```

After the owner removes the share row directly in the database, the reader's next request gets 404: the share is looked up fresh on every request, not remembered.

### Line by line: `tests/security/test_audit.py`

```python
"""Stretch: security events are logged and recorded in an append-only table."""
```

The docstring: security events are logged and recorded in an append-only table.

```python
import json

import psycopg
import pytest

from tests.support import HOSTILE, Browser, new_password, new_username

pytestmark = pytest.mark.security
```

Imports (`json`, `psycopg` for its error classes, `pytest`, the helpers) and the marker.

```python
def _audit_lines(captured_logs):
    lines = [json.loads(line) for line in captured_logs.getvalue().splitlines() if line.startswith("{")]
    return [line for line in lines if line.get("message") == "audit"]
```

`_audit_lines` parses the captured log lines that start with `{` as JSON and keeps the ones whose message is `audit`.

```python
def test_a_denied_note_access_writes_a_log_line_and_an_audit_row(app, owner_sql, captured_logs):
    intruder, owner = Browser(app), Browser(app)
    intruder.register("intruder")
    owner.register("owner")
    note_id = owner.create_note("Private", HOSTILE)
    assert intruder.api("GET", f"/notes/{note_id}", csrf=None).status_code == 404

    denied = [line for line in _audit_lines(captured_logs) if line["action"] == "note.access_denied"]
    assert len(denied) == 1
    assert denied[0]["note_id"] == str(note_id)
    assert denied[0]["reason"] == "no_access"
    rows = owner_sql("SELECT action, outcome, detail FROM audit_events WHERE action = 'note.access_denied'")
    assert rows == [("note.access_denied", "refused", {"note_id": str(note_id), "reason": "no_access"})]
    assert "script" not in captured_logs.getvalue()  # note content never reaches the log
```

An intruder asks for the owner's private note (whose content is the hostile text). The log has exactly one `note.access_denied` line with the note id and reason `no_access`; the table has exactly one matching row with its detail as a dictionary; and the word `script` appears nowhere in the logs, so note content never reaches them.

```python
def test_sign_up_sign_in_failure_and_sign_out_are_audited(app, owner_sql):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    browser.sign_in(username, "wrong password here!!")
    browser.sign_in(username, password)
    browser.post("/logout", data={"csrf_token": browser.csrf_token()})
    actions = [row[0] for row in owner_sql("SELECT action FROM audit_events ORDER BY id")]
    assert actions == ["signup", "login.failure", "login.success", "logout"]
```

After sign-up, a failed sign-in, a good sign-in and a logout, the audit actions in order are `signup`, `login.failure`, `login.success`, `logout`.

```python
def test_a_forged_request_is_audited(app, owner_sql):
    browser = Browser(app)
    browser.register()
    browser.api("POST", "/notes", json={"title": "x", "content": "y"}, csrf="forged")
    rows = owner_sql("SELECT action, detail FROM audit_events WHERE action = 'csrf.rejected'")
    assert rows == [("csrf.rejected", {"method": "POST", "path": "/notes"})]
```

A request with a forged CSRF token writes one `csrf.rejected` row with the method and the path.

```python
def test_audit_detail_holds_only_ids_and_reasons(app, owner_sql):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    browser.sign_in(username, password)
    browser.sign_in("' OR '1'='1", "another wrong password")
    dump = json.dumps(owner_sql("SELECT user_id, ip, detail::text FROM audit_events"), default=str)
    assert username not in dump
    assert password not in dump
    assert "OR '1'" not in dump
```

After a sign-up, a sign-in and a failed sign-in with a SQL-looking username, the whole audit table dumped as JSON contains neither the username, nor the password, nor the SQL text: detail holds only ids and reasons.

```python
def test_the_application_role_cannot_change_or_delete_audit_rows(container, owner_sql):
    owner_sql("INSERT INTO audit_events (action, outcome, ip) VALUES ('signup', 'success', '127.0.0.1')")
    with container.database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (1,)
    for statement in (
        "UPDATE audit_events SET outcome = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), container.database.connection() as connection:
            connection.execute(statement)
    assert owner_sql("SELECT outcome FROM audit_events") == [("success",)]
```

Using the application's own connection, one inserted row can be counted, but `UPDATE`, `DELETE` and `TRUNCATE` each raise `InsufficientPrivilege`, and the row is unchanged.

```python
def test_even_the_owner_role_cannot_rewrite_history_with_update_or_delete(owner_sql):
    owner_sql("INSERT INTO audit_events (action, outcome, ip) VALUES ('signup', 'success', '127.0.0.1')")
    for statement in ("UPDATE audit_events SET outcome = 'tampered'", "DELETE FROM audit_events"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            owner_sql(statement)
```

Even the owner role cannot update or delete a row: the trigger raises an `insufficient_privilege` error whose message contains "append-only".

### Line by line: `tests/security/test_injection.py`

```python
"""Step 3: parameterized queries and output encoding."""
```

The docstring: step 3, parameterized queries and output encoding.

```python
import pytest

from tests.support import HOSTILE, Browser, new_password, new_username

pytestmark = pytest.mark.security
```

Imports and the marker.

```python
def test_hostile_content_is_stored_exactly_as_text(browser, owner_sql):
    browser.register()
    note_id = browser.create_note(title="It's a 'quoted' title", content=HOSTILE)
    stored = owner_sql("SELECT title, content FROM notes WHERE id = %s", (note_id,))
    assert stored == [("It's a 'quoted' title", HOSTILE)]  # stored exactly, no SQL side effect from the quote
    assert owner_sql("SELECT count(*) FROM notes") == [(1,)]
    assert owner_sql("SELECT count(*) FROM users") == [(1,)]  # the rest of the database is untouched
```

A note with a quoted title and the hostile content is created. The database stores them exactly, there is one note and one user: the quote had no SQL side effect. `UNSAFE_SQL_CONCATENATION` must break this test.

```python
def test_hostile_content_is_rendered_as_inert_text(app, owner_sql):
    browser = Browser(app)
    username, _ = browser.register()
    owner_id = owner_sql("SELECT id FROM users WHERE username = %s", (username,))[0][0]
    # Inserted through the owner connection so this test isolates output encoding from query construction.
    note_id = owner_sql(
        "INSERT INTO notes (owner_id, title, content) VALUES (%s, %s, %s) RETURNING id",
        (owner_id, "<b>bold</b> title", HOSTILE),
    )[0][0]

    page = browser.get(f"/notes/{note_id}").get_data(as_text=True)
    assert "<script>" not in page  # the literal tag characters never appear unescaped
    assert "&lt;script&gt;" in page  # it was encoded, not stripped or executed
    listing = browser.get("/notes").get_data(as_text=True)
    assert "<b>bold</b>" not in listing
    assert "&lt;b&gt;bold&lt;/b&gt;" in listing
    json_page = browser.api("GET", f"/notes/{note_id}", csrf=None)
    assert json_page.content_type == "application/json"  # JSON is data, never rendered as markup
```

To test output encoding alone, the note is inserted straight through the owner connection (so query construction plays no part). The page for the note contains no literal `<script>` but does contain `&lt;script&gt;`; the list shows the title `<b>bold</b>` encoded; and the JSON version has content type `application/json`. `UNSAFE_RAW_NOTE_OUTPUT` must break the HTML checks.

```python
def test_sql_metacharacters_in_the_sign_in_form_are_just_a_failed_sign_in(app, owner_sql):
    browser = Browser(app)
    browser.sign_up(new_username(), new_password())
    for username in ("' OR '1'='1' --", "admin'; DROP TABLE users; --"):
        response = browser.sign_in(username, "' OR '1'='1")
        assert response.status_code == 401
    assert owner_sql("SELECT count(*) FROM users") == [(1,)]
```

Two SQL-injection usernames in the sign-in form each give 401 and the `users` table still has its one row.

```python
def test_a_note_content_with_a_percent_and_a_backslash_round_trips(browser, owner_sql):
    browser.register()
    awkward = r"100% of C:\temp\new and %s and {0}"
    note_id = browser.create_note(content=awkward)
    assert owner_sql("SELECT content FROM notes WHERE id = %s", (note_id,)) == [(awkward,)]
```

Content with a percent sign, a backslash, `%s` and `{0}` (characters that placeholders and format strings treat specially) round-trips unchanged through the database.

### Line by line: `tests/integration/test_database.py`

These tests need the real database (`make up`) and carry the marker `integration`.

```python
"""The pool, the probe and the privileges of the application's database role."""
```

The docstring: the pool, the probe and the privileges of the application's database role.

```python
import psycopg
import pytest
from psycopg_pool import PoolTimeout

from notes_app.infrastructure.postgres.database import Database
from notes_app.infrastructure.settings import DatabaseSettings
```

Imports: `psycopg` (for error classes), `pytest`, `PoolTimeout` (the error psycopg_pool raises when the pool cannot get its connections in time), the pool wrapper and the settings class.

```python
pytestmark = pytest.mark.integration
```

The `integration` marker for the whole file.

```python
def test_ping_is_true_while_open_and_false_after_close(container):
    assert container.database.ping() is True
    container.database.close()
    assert container.database.ping() is False
```

`ping` is true while the pool is open and false after `close()`.

```python
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
```

The settings of the real database are copied except for a wrong password and a 2-second connect timeout. Opening the pool must raise `PoolTimeout`: a wrong password stops start-up. `database.close()` then tidies up.

```python
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
```

`parametrize` runs the test for five statements an attacker would try: create a table, drop `users`, add an `is_admin` column, truncate `users`, create a role. Each, run through the application's own connection, must raise `InsufficientPrivilege`: the role cannot change the schema.

```python
def test_the_application_role_can_do_ordinary_work(container):
    with container.database.connection() as connection:
        connection.execute("INSERT INTO users (username, password_hash) VALUES ('worker', 'h')")
        assert connection.execute("SELECT count(*) FROM users").fetchone() == (1,)
```

Ordinary work is allowed: the application role inserts a user and counts one row.

### Line by line: `tests/integration/test_repositories.py`

```python
"""The PostgreSQL adapters against the real database (make up)."""
```

The docstring: the PostgreSQL adapters against the real database.

```python
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
```

Imports: time types, `psycopg` and `pytest`.

```python
from notes_app.domain.errors import LoginThrottledError, UsernameTakenError
from notes_app.domain.models import AuditAction, AuditEvent, NoteRole, Session
from notes_app.infrastructure.postgres.audit import PostgresAuditLog
from notes_app.infrastructure.postgres.notes import PostgresNoteRepository
from notes_app.infrastructure.postgres.sessions import PostgresSessionRepository
from notes_app.infrastructure.postgres.throttle import PostgresLoginThrottle
from notes_app.infrastructure.postgres.users import PostgresUserRepository
```

Imports of two errors, the models and all five repositories.

```python
pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
```

The `integration` marker and a fixed `NOW`.

```python
@pytest.fixture
def users(container):
    return PostgresUserRepository(container.database)


@pytest.fixture
def notes(container):
    return PostgresNoteRepository(container.database)
```

Two fixtures build the user and note repositories on the container's pool.

```python
def test_users_are_added_found_and_rehashed(users):
    alice = users.add("alice", "hash-1")
    assert users.by_username("alice") == alice
    assert users.by_id(alice.id) == alice
    assert users.by_username("nobody") is None
    assert users.by_id(999) is None
    users.update_password_hash(alice.id, "hash-2")
    assert users.by_id(alice.id).password_hash == "hash-2"
```

Add a user; find by name and by id (equal to the added one); unknown name and id give `None`; update the hash and read it back.

```python
def test_the_unique_constraint_not_a_lookup_refuses_a_duplicate_username(users):
    users.add("alice", "hash")
    with pytest.raises(UsernameTakenError):
        users.add("alice", "another-hash")
```

Adding the same name twice raises `UsernameTakenError`: the database's unique rule decides.

```python
def test_the_schema_rejects_a_username_outside_the_allow_list(container):
    with pytest.raises(psycopg.errors.CheckViolation), container.database.connection() as connection:
        connection.execute("INSERT INTO users (username, password_hash) VALUES ('Bad Name', 'x')")
```

Inserting the username `Bad Name` directly is rejected by the table's `CHECK` (`CheckViolation`), proving the schema repeats the allow-list.

```python
def test_notes_are_created_read_updated_and_deleted_with_their_shares(users, notes):
    owner, reader = users.add("owner", "h"), users.add("reader", "h")
    note = notes.add(owner.id, "Title", "Content")
    assert notes.get(note.id) == note
    assert notes.get(999) is None
    notes.share(note.id, reader.id)
    notes.share(note.id, reader.id)  # idempotent
    assert notes.shared_with(note.id) == frozenset({reader.id})
    updated = notes.update(note.id, "New", "Changed")
    assert (updated.title, updated.content) == ("New", "Changed")
    assert updated.updated_at >= note.updated_at
    notes.delete(note.id)
    assert notes.get(note.id) is None
    assert notes.shared_with(note.id) == frozenset()
```

A note's life: created, read, unknown id gives `None`, shared twice (a no-op the second time), the share list has the reader, updated (the update time never goes backward), deleted, and after the delete the note and its shares are gone (the cascade).

```python
def test_the_visible_list_has_owned_and_shared_notes_with_roles_newest_first(users, notes):
    alice, bob, carol = users.add("alice", "h"), users.add("bob", "h"), users.add("carol", "h")
    first = notes.add(alice.id, "First", "x")
    second = notes.add(bob.id, "Second", "y")
    notes.add(carol.id, "Hidden", "z")
    notes.share(second.id, alice.id)
    visible = notes.list_visible(alice.id)
    assert [(item.note.id, item.role, item.owner_username) for item in visible] == [
        (second.id, NoteRole.READER, "bob"),
        (first.id, NoteRole.OWNER, "alice"),
    ]
```

Alice owns "First", Bob owns "Second" shared with Alice, Carol owns a hidden one. Alice's list has "Second" as `READER` with owner `bob` first (newest) and "First" as `OWNER`; Carol's note is absent.

```python
def test_a_title_over_the_limit_is_refused_by_the_database_too(users, notes):
    owner = users.add("owner", "h")
    with pytest.raises(psycopg.errors.CheckViolation):
        notes.add(owner.id, "x" * 121, "content")
```

A 121-character title is refused by the database as well (`CheckViolation`).

```python
def test_sessions_round_trip_and_touch(container):
    sessions = PostgresSessionRepository(container.database)
    session = Session("hash-1", None, "csrf", NOW, NOW, NOW + timedelta(hours=1))
    sessions.add(session)
    assert sessions.get("hash-1") == session
    sessions.touch("hash-1", NOW + timedelta(minutes=5))
    touched = sessions.get("hash-1")
    assert touched is not None
    assert touched.last_seen_at == NOW + timedelta(minutes=5)
    sessions.delete("hash-1")
    assert sessions.get("hash-1") is None
```

A session is added, read back equal, touched (the new last-seen time is stored), deleted and then gone.

```python
def test_purging_removes_only_expired_sessions(container):
    sessions = PostgresSessionRepository(container.database)
    sessions.add(Session("old", None, "c", NOW, NOW, NOW - timedelta(seconds=1)))
    sessions.add(Session("live", None, "c", NOW, NOW, NOW + timedelta(hours=1)))
    assert sessions.purge_expired(NOW) == 1
    assert sessions.get("old") is None
    assert sessions.get("live") is not None
```

Two sessions, one expired a second ago and one valid for an hour: `purge_expired` removes exactly one and keeps the live one.

```python
def test_the_throttle_counts_per_key_ages_out_and_resets(container):
    throttle = PostgresLoginThrottle(container.database, max_failures=2, window_seconds=600)
    throttle.record_failure("ip|alice", NOW)
    throttle.check("ip|alice", NOW)
    throttle.record_failure("ip|alice", NOW + timedelta(seconds=1))
    with pytest.raises(LoginThrottledError) as refused:
        throttle.check("ip|alice", NOW + timedelta(seconds=2))
    assert 595 <= refused.value.retry_after_seconds <= 600
    throttle.check("ip|bob", NOW + timedelta(seconds=2))  # another key is unaffected
    throttle.check("ip|alice", NOW + timedelta(seconds=602))  # the failures aged out
    throttle.reset("ip|alice")
    throttle.check("ip|alice", NOW + timedelta(seconds=2))
```

With a limit of 2 in 600 seconds: one failure is fine; after two failures the check raises with a wait between 595 and 600 seconds; another key (`ip|bob`) is unaffected; 602 seconds later the failures have aged out; after `reset` the key is clear again.

```python
def test_recording_a_failure_prunes_rows_that_left_every_window(container, owner_sql):
    throttle = PostgresLoginThrottle(container.database, max_failures=5, window_seconds=600)
    throttle.record_failure("ip|alice", NOW)
    throttle.record_failure("ip|alice", NOW + timedelta(hours=1))
    assert owner_sql("SELECT count(*) FROM login_failures") == [(1,)]
```

Recording a failure an hour after the first prunes the old row: only one row remains.

```python
def test_an_audit_event_is_stored_with_its_detail(container, owner_sql):
    PostgresAuditLog(container.database).record(
        AuditEvent(AuditAction.NOTE_SHARED, "success", None, "10.0.0.1", (("note_id", "7"),))
    )
    assert owner_sql("SELECT action, outcome, user_id, ip, detail FROM audit_events") == [
        ("note.shared", "success", None, "10.0.0.1", {"note_id": "7"})
    ]
```

An audit event is stored with its action, outcome, a null user id, the IP and the detail as a dictionary.

```python
def test_a_failing_audit_write_is_logged_and_does_not_fail_the_request(container, caplog, monkeypatch):
    def broken():
        raise psycopg.OperationalError("database went away")

    monkeypatch.setattr(container.database, "connection", broken)
    PostgresAuditLog(container.database).record(AuditEvent(AuditAction.LOGOUT, "success", 1, "10.0.0.1"))
    assert "audit row could not be written" in caplog.text
```

The test replaces the pool's `connection` method with a function that raises `OperationalError`, using `monkeypatch` (which undoes the change after the test). Recording an event still does not raise, and `caplog` (pytest's log capture) shows the message "audit row could not be written".

### Line by line: `tests/e2e/test_scenario.py`

```python
"""The lesson's scenario over real HTTP against a server process started the way production starts it."""
```

The docstring: the lesson's scenario over real HTTP against a server process started the way production starts it. "End to end" means through the real server, not a test client.

```python
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
```

Imports: `os`, `signal` (to send SIGTERM), `socket`, `subprocess`, `sys`, `time`, `urllib.request` and `pytest`.

```python
from notes_app.interfaces.demo_cli import run_scenario

pytestmark = pytest.mark.e2e
```

The scenario runner of the demo, which is reused here, and the marker `e2e`.

```python
STARTUP_SECONDS = 180  # generous: a loaded CI runner or laptop boots two workers slowly
SERVE = [
    sys.executable,
    "-m",
    "gunicorn",
    "-c",
    "python:notes_app.interfaces.gunicorn_conf",
    "notes_app.interfaces.wsgi:build_app()",
]
```

`STARTUP_SECONDS` is 180 (a loaded machine boots two workers slowly). `SERVE` is the command as a list: the current Python running gunicorn with the configuration module and the app factory.

```python
def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
```

`_free_port` asks the operating system for a free port: it binds to port 0 on the loopback address (which means "pick any") and reads the number assigned.

```python
def _environment(port: int, **extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("UNSAFE_")}
    env.update({"APP_ENV": "development", "APP_HOST": "127.0.0.1", "APP_PORT": str(port), "WEB_CONCURRENCY": "2"})
    env.update(extra)
    return env
```

`_environment` copies the environment without any `UNSAFE_*` variable, sets development mode, loopback host, the free port and two workers, then adds any extra variables.

```python
def _wait_until_ready(port: int, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        assert server.poll() is None, "the server exited before it was ready"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise AssertionError(f"the server did not become ready in {STARTUP_SECONDS} seconds")
```

`_wait_until_ready` polls `/readyz` until it answers 200 or the deadline passes (`time.monotonic` is a clock that never goes backward). Each loop first asserts the server process has not exited (`poll()` returns `None` while it runs). A connection error sleeps half a second and retries; running out of time raises an `AssertionError`.

```python
@pytest.fixture
def server():
    port = _free_port()
    process = subprocess.Popen(SERVE, env=_environment(port), stderr=subprocess.PIPE, text=True)  # noqa: S603
    try:
        _wait_until_ready(port, process)
        yield port, process
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=60)
```

The `server` fixture picks a port, starts gunicorn as a child process with standard error piped, waits until ready, hands the port and process to the test and, in `finally`, sends SIGTERM and waits up to 60 seconds if it is still running. `# noqa: S603` tells ruff the subprocess call is safe (an argument list).

```python
def test_the_scenario_passes_against_two_workers(server):
    port, _ = server
    steps = run_scenario("127.0.0.1", port)
    assert [step.name for step in steps if not step.passed] == []
    assert len(steps) >= 8
```

The scenario from the demo runs against the two-worker server: no step failed and there are at least 8 steps.

```python
def test_sigterm_shuts_the_server_down_cleanly_and_closes_the_database_pool(server):
    _, process = server
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=60) == 0
    log = process.stderr.read()
    assert "Handling signal: term" in log
    assert log.count("database pool closed") == 2  # one per worker
    assert "Shutting down: Master" in log
```

SIGTERM makes the server exit with code 0; its log shows "Handling signal: term", exactly two lines "database pool closed" (one per worker) and "Shutting down: Master".

```python
def test_the_server_refuses_to_start_with_a_deliberate_weakness_outside_the_test_environment():
    process = subprocess.run(  # noqa: S603
        SERVE,
        env=_environment(_free_port(), UNSAFE_SKIP_CSRF="1"),
        capture_output=True,
        text=True,
        timeout=STARTUP_SECONDS,
        check=False,
    )
    assert process.returncode != 0
    assert "only accepted when APP_ENV=test" in process.stderr
```

Starting with `UNSAFE_SKIP_CSRF=1` while `APP_ENV=development` must fail: a non-zero exit and the message "only accepted when APP_ENV=test" on standard error.

```python
def test_the_server_refuses_to_start_without_a_database_password():
    env = _environment(_free_port())
    env.pop("NOTES_DB_PASSWORD", None)
    process = subprocess.run(SERVE, env=env, capture_output=True, text=True, timeout=STARTUP_SECONDS, check=False)  # noqa: S603
    assert process.returncode != 0
    assert "NOTES_DB_PASSWORD is required" in process.stderr
```

Starting without a database password must fail: a non-zero exit and the message "NOTES_DB_PASSWORD is required".

## Try it yourself

1. Run the fast tests:
   ```bash
   make test
   ```
   Expect `96 passed` and the coverage table ending with `TOTAL ... 100%` for domain and application.
2. See the list of tests without running them:
   ```bash
   .venv/bin/pytest --collect-only -q tests | tail -3
   ```
   Expect `153 tests collected`.
3. Run one test by name:
   ```bash
   .venv/bin/pytest tests/unit/test_throttle.py::test_the_wait_is_never_less_than_one_second -v
   ```
   Expect one `PASSED`.
4. Make a test fail and read the output (then revert): in `src/notes_app/domain/throttle.py` change `+ 1` to `+ 0` in the `return max(...)` line and run `.venv/bin/pytest tests/unit/test_throttle.py`. Expect failures such as `assert 590 == 591`. Restore with `git checkout src/notes_app/domain/throttle.py`.
5. With `make up`, run the security tests: `make test-security`. Expect 33 passed.

## Mistakes people make

- Tests that depend on each other's leftovers. Here every database test starts from `reset.sql`.
- Tests with no assertion, or assertions that cannot fail. The removal proof (`make prove`) checks the guarding ones.
- Real secrets in tests. Passwords are generated per test (`secrets.token_urlsafe`) and never written down.
- Slow unit tests. Fakes and cheap argon2 settings keep the suite at a few seconds.
- Chasing 100% coverage everywhere. The gate applies to the domain and application, where logic lives.
- Leaving a test server running when a fixture fails. The e2e fixture uses try/finally.

## Check yourself

1. How does pytest know a parameter is a fixture?
   *Its name matches a fixture function visible from the test.*
2. What does code after `yield` in a fixture do?
   *Runs as clean-up after the test, even when it failed.*
3. What does `--strict-markers` prevent?
   *Typos in marker names silently creating new markers.*
4. Why can the domain be tested without a database?
   *It imports nothing outside the standard library, and the application is tested against in-memory fakes of the ports.*
5. What does `--fail-under=95` do?
   *Makes the command fail when coverage of the chosen files is below 95%.*

## Further reading

- pytest 9 documentation: https://docs.pytest.org/en/stable/
- Fixtures: https://docs.pytest.org/en/stable/how-to/fixtures.html
- Markers: https://docs.pytest.org/en/stable/how-to/mark.html
- pytest-cov 7: https://pytest-cov.readthedocs.io/en/latest/
- coverage.py: https://coverage.readthedocs.io/
