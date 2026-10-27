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
