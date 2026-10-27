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
