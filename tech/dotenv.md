# `.env` files and environment variables

## What it is

An **environment variable** is a named text value that the operating system hands to every program it starts (`PATH`, `HOME`). Programs read them to find out how they should behave. A **`.env` file** is a plain text file of `NAME=value` lines used by tools to set many variables at once. It is a convention, not a standard, and different tools read it slightly differently.

## Why this repository uses it

Rule one of the lesson: **no secret in code**. Passwords and tuning settings come from the environment, the app refuses to start when a required one is missing, and the real values live in a git-ignored `.env`. The twelve-factor app method calls this "config in the environment".

## Where it appears

| Path | What it does |
| --- | --- |
| `.env.example` | The tracked template with safe local-only placeholder values. |
| `.env` | Your local copy, created by `make env`; git-ignored and excluded from Docker builds. |
| `Makefile` | `-include .env` and `export`: make reads the file and passes the values to every recipe. |
| `docker-compose.yml` | Substitutes `${VAR}` placeholders from `.env` and loads it into the app container with `env_file`. |
| `src/notes_app/infrastructure/settings.py` | `Settings.from_environment(os.environ)` reads, validates and types everything. |
| `tests/conftest.py` | Supplies defaults for the test run and forces `APP_ENV=test`. |

(The `.env*` files are deliberately not displayed in this note: the editor environment denies reading them, and they hold credentials. Variable names below come from the code.)

## How it works underneath

1. When a program starts, the parent process passes a copy of its environment (a dictionary of strings) to the child. Changes made by the child do not flow back.
2. `make` with `-include .env` parses the `NAME=value` lines as Make variables; `export` puts them into the environment of recipes.
3. Docker Compose reads `.env` from the project folder for `${...}` substitution, and `env_file:` injects every line into a container's environment.
4. In Python, `os.environ` is that dictionary. Every value is a string; the code converts and validates (`int(...)`, allowed sets).

### Ideas you need first

- **A process and its environment.** Every running program (process) receives, when it starts, a private copy of a list of `NAME=value` pairs called its environment. Programs read them to learn how they should behave.
- **A string.** All environment values are text, even `8047`; a program that wants a number must convert it, and a bad value must be rejected at start-up.
- **A default.** A value used when the variable is not set. `${NAME:-default}` in Compose and `env.get("NAME", default)` in Python both mean that.
- **A secret.** A value that must stay private (a password, a key). Plain settings may be shared; secrets must not be committed.
- **A template file.** `.env.example` has every name and safe local values and is committed; `.env` is your own copy and is not.

## Walkthrough of this repository's use

The variables the application understands (from `settings.py`):

| Variable | Meaning | Default |
| --- | --- | --- |
| `APP_ENV` | `development`, `test` or `production` | `production` |
| `APP_HOST`, `APP_PORT` | Where to listen | `127.0.0.1`, `8047` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `TRUSTED_PROXY_COUNT` | Reverse proxies whose forwarded headers to believe | `0` |
| `NOTES_DB_HOST`, `NOTES_DB_PORT`, `NOTES_DB_NAME`, `NOTES_DB_USER` | Database connection | `localhost`, `5471`, `notes`, `notes_app` |
| `NOTES_DB_PASSWORD` | **Required**; the limited role's password | none |
| `NOTES_DB_POOL_MIN`, `NOTES_DB_POOL_MAX` | Connection pool size | `1`, `8` |
| `ARGON2_TIME_COST`, `ARGON2_MEMORY_KIB`, `ARGON2_PARALLELISM` | Password-hash cost | `2`, `19456`, `1` |
| `SESSION_IDLE_SECONDS`, `SESSION_ABSOLUTE_SECONDS`, `ANONYMOUS_SESSION_SECONDS` | Session lifetimes | `1800`, `28800`, `900` |
| `LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_SECONDS` | Throttle | `5`, `900` |
| `UNSAFE_*` | The deliberate weaknesses; refused unless `APP_ENV=test` | off |
| `WEB_CONCURRENCY` | gunicorn workers | `2` |

Compose also uses `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` for the database container.

Key behaviors in code:

```python
password = env.get("NOTES_DB_PASSWORD", "")
if not password:
    raise ConfigError("NOTES_DB_PASSWORD is required (set it in .env or the environment)")
```
No default password exists anywhere: a missing one stops start-up with a clear message.

```python
def _read_int(env, name, default, *, minimum=1) -> int:
    ...
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
```
A typo in a number is an error at start-up, not a crash in the middle of a request.

`Settings._validate` also refuses weak argon2 values and any `UNSAFE_*` weakness outside `APP_ENV=test`, so a copied-over test configuration cannot weaken production.

Where the format differs between tools: the `Makefile` and Compose both accept simple `NAME=value` lines; avoid quotes, spaces around `=`, and `$` in values, which they treat differently.

### Line by line: `src/notes_app/infrastructure/settings.py`

```python
"""Configuration from the environment (twelve-factor), validated once at start-up."""
```

The docstring: configuration from the environment (the twelve-factor method), validated once at start-up.

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Literal

from notes_app.application.sessions import SessionPolicy
```

Imports: `Mapping`, `dataclass`, `field` and `fields` (to list a dataclass's fields), `Literal` and `SessionPolicy`.

```python
AppEnv = Literal["development", "test", "production"]
_ENVIRONMENTS: tuple[AppEnv, ...] = ("development", "test", "production")
_TRUE = {"1", "true", "yes", "on"}
```

`AppEnv` is a type that allows exactly three texts; `_ENVIRONMENTS` lists them; `_TRUE` is the set of texts that count as "on".

```python
# The OWASP Password Storage Cheat Sheet minimum for argon2id (19 MiB, 2 iterations, 1 lane).
ARGON2_MIN_TIME_COST = 2
ARGON2_MIN_MEMORY_KIB = 19_456
```

The comment cites the OWASP minimum for argon2id: 19 MiB of memory, 2 iterations, 1 lane. `19_456` is 19 times 1,024 kibibytes.

```python
class ConfigError(Exception):
    """A setting is missing or invalid. Raised before the app serves anything."""
```

`ConfigError` is raised before the app serves anything.

```python
def _read_int(env: Mapping[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value
```

`_read_int` returns the default for a missing or empty variable, raises `ConfigError` for text that is not a whole number or is below the minimum (`minimum` is keyword-only).

```python
@dataclass(frozen=True, slots=True)
class Weaknesses:
    """Deliberate weaknesses, one per control of the threat model, all off by default.

    They exist so the test suite can prove each control by running the same tests with the control removed and
    watching them fail. They are only accepted when ``APP_ENV=test``.
    """
```

`Weaknesses` holds the deliberate weaknesses, one per control, all false by default. The docstring: they let the tests prove each control by running with it removed, and they are accepted only when `APP_ENV=test`.

```python
    weak_password_hash: bool = False
    sql_concatenation: bool = False
    raw_note_output: bool = False
    skip_ownership_check: bool = False
    weak_session_cookie: bool = False
    skip_csrf: bool = False
    skip_security_headers: bool = False
```

The seven switches: weak password hash, SQL concatenation, raw note output, skipped ownership check, weak session cookie, skipped CSRF and skipped security headers.

```python
    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Weaknesses:
        """Read ``UNSAFE_<NAME>`` variables; anything but 1, true, yes or on means off."""
        return cls(**{f.name: env.get(f"UNSAFE_{f.name.upper()}", "").lower() in _TRUE for f in fields(cls)})
```

`from_environment` reads `UNSAFE_<NAME>` for each field (the field name in upper case); only `1`, `true`, `yes` or `on` (any capitalization) turn it on.

```python
    def enabled(self) -> tuple[str, ...]:
        """The names of the weaknesses that are switched on."""
        return tuple(f.name for f in fields(self) if getattr(self, f.name))
```

`enabled` lists the names that are on.

```python
@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Connection settings of the application's limited PostgreSQL role."""

    host: str
    port: int
    name: str
    user: str
    password: str = field(repr=False)
    pool_min: int = 1
    pool_max: int = 8
    connect_timeout_seconds: int = 5
```

`DatabaseSettings` holds host, port, name, user, password, pool sizes and the connect timeout. `field(repr=False)` keeps the password out of the printed form.

```python
    def conninfo(self) -> str:
        """A libpq connection string. Contains the password; never log it."""
        return (
            f"host={self.host} port={self.port} dbname={self.name} user={self.user} "
            f"password={self.password} connect_timeout={self.connect_timeout_seconds}"
        )
```

`conninfo` builds the libpq connection string including the password; its docstring says never to log it.

```python
@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the application reads from its environment."""

    app_env: AppEnv
    host: str
    port: int
    log_level: str
    trusted_proxy_count: int
    database: DatabaseSettings
    argon2_time_cost: int
    argon2_memory_kib: int
    argon2_parallelism: int
    session: SessionPolicy
    login_max_failures: int
    login_window_seconds: int
    weaknesses: Weaknesses
```

`Settings` gathers every setting: environment name, host and port, log level, trusted proxy count, database, the three argon2 numbers, the session lifetimes, the login limit and window, and the weaknesses.

```python
    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> Settings:
        """Build and validate settings; raise ``ConfigError`` naming the first problem."""
        app_env = env.get("APP_ENV", "production")
        if app_env not in _ENVIRONMENTS:
            raise ConfigError(f"APP_ENV must be one of {', '.join(_ENVIRONMENTS)}, got {app_env!r}")
        password = env.get("NOTES_DB_PASSWORD", "")
        if not password:
            raise ConfigError("NOTES_DB_PASSWORD is required (set it in .env or the environment)")
```

`from_environment` checks `APP_ENV` (default `production`, the safe default) and refuses to start without `NOTES_DB_PASSWORD`: there is no default password.

```python
        settings = cls(
            app_env=app_env,
            host=env.get("APP_HOST", "127.0.0.1"),
            port=_read_int(env, "APP_PORT", 8047),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            trusted_proxy_count=_read_int(env, "TRUSTED_PROXY_COUNT", 0, minimum=0),
            database=DatabaseSettings(
                host=env.get("NOTES_DB_HOST", "localhost"),
                port=_read_int(env, "NOTES_DB_PORT", 5471),
                name=env.get("NOTES_DB_NAME", "notes"),
                user=env.get("NOTES_DB_USER", "notes_app"),
                password=password,
                pool_min=_read_int(env, "NOTES_DB_POOL_MIN", 1),
                pool_max=_read_int(env, "NOTES_DB_POOL_MAX", 8),
            ),
            argon2_time_cost=_read_int(env, "ARGON2_TIME_COST", ARGON2_MIN_TIME_COST),
            argon2_memory_kib=_read_int(env, "ARGON2_MEMORY_KIB", ARGON2_MIN_MEMORY_KIB),
            argon2_parallelism=_read_int(env, "ARGON2_PARALLELISM", 1),
            session=SessionPolicy(
                idle_seconds=_read_int(env, "SESSION_IDLE_SECONDS", 1800),
                absolute_seconds=_read_int(env, "SESSION_ABSOLUTE_SECONDS", 28800),
                anonymous_seconds=_read_int(env, "ANONYMOUS_SESSION_SECONDS", 900),
            ),
            login_max_failures=_read_int(env, "LOGIN_MAX_FAILURES", 5),
            login_window_seconds=_read_int(env, "LOGIN_WINDOW_SECONDS", 900),
            weaknesses=Weaknesses.from_environment(env),
        )
```

It builds the object, reading each variable with its default: host `127.0.0.1`, port 8047, log level `INFO`, trusted proxies 0 (minimum 0), database `localhost:5471/notes` as `notes_app`, pool 1 to 8, argon2 at the OWASP minimum, session idle 1800 s, absolute 28800 s, anonymous 900 s, five failures in a 900 s window, and the weaknesses.

```python
        settings._validate()
        return settings
```

`_validate` runs, then the settings are returned.

```python
    def _validate(self) -> None:
        enabled = self.weaknesses.enabled()
        if enabled and self.app_env != "test":
            raise ConfigError(f"deliberate weaknesses ({', '.join(enabled)}) are only accepted when APP_ENV=test")
```

If any weakness is on outside `APP_ENV=test`, startup is refused, so a copied test configuration cannot weaken production.

```python
        weak_argon2 = self.argon2_time_cost < ARGON2_MIN_TIME_COST or self.argon2_memory_kib < ARGON2_MIN_MEMORY_KIB
        if weak_argon2 and self.app_env != "test":
            raise ConfigError(
                f"argon2 parameters are below the OWASP minimum ({ARGON2_MIN_TIME_COST} iterations, "
                f"{ARGON2_MIN_MEMORY_KIB} KiB)"
            )
```

Argon2 parameters below the OWASP minimum are refused outside test mode.

```python
        if self.database.pool_min > self.database.pool_max:
            raise ConfigError("NOTES_DB_POOL_MIN must not exceed NOTES_DB_POOL_MAX")
        if self.session.anonymous_seconds > self.session.absolute_seconds:
            raise ConfigError("ANONYMOUS_SESSION_SECONDS must not exceed SESSION_ABSOLUTE_SECONDS")
```

The pool minimum may not exceed the maximum, and the anonymous session may not outlive the absolute session.

## Try it yourself

1. Create the file and see it is ignored:
   ```bash
   make env && git status --short | grep -c "\.env$"
   ```
   Expect `created .env from .env.example` (or nothing if it exists) and `0`: git does not see `.env`.
2. Prove the app refuses to start without a password:
   ```bash
   env -u NOTES_DB_PASSWORD .venv/bin/python -c "
   import os
   from notes_app.infrastructure.settings import Settings
   Settings.from_environment({'APP_ENV': 'development'})"
   ```
   Expect `ConfigError: NOTES_DB_PASSWORD is required (set it in .env or the environment)`.
3. Prove weaknesses are refused in production mode:
   ```bash
   .venv/bin/python -c "
   from notes_app.infrastructure.settings import Settings
   Settings.from_environment({'NOTES_DB_PASSWORD': 'x', 'UNSAFE_SKIP_CSRF': '1'})"
   ```
   Expect `ConfigError: deliberate weaknesses (skip_csrf) are only accepted when APP_ENV=test`.
4. Run the settings tests: `.venv/bin/pytest tests/unit/test_settings.py -q`. Expect all pass.

## Mistakes people make

- Committing `.env`. It is ignored and excluded from images.
- Giving production a default password "for convenience".
- Treating all variables as strings and finding out at 3 a.m. that `"false"` is truthy. Here parsing is explicit.
- Printing the environment or settings in logs. `DatabaseSettings.password` is `repr=False`, and the log formatter redacts sensitive names.
- Assuming a child can change a parent's variables.

## Check yourself

1. What type is every environment variable's value?
   *A string.*
2. Why does `Settings.from_environment` take a mapping argument?
   *So tests can pass their own dictionary instead of changing the real environment.*
3. What does `-include .env` followed by `export` do in the Makefile?
   *Reads the file into Make variables and passes them to every recipe's environment.*
4. What happens when `NOTES_DB_PASSWORD` is missing?
   *`ConfigError` at start-up, before anything is served.*
5. Why is `.env.example` safe to commit?
   *It contains only local-only placeholders, never real credentials.*

## Further reading

- The Twelve-Factor App, config: https://12factor.net/config
- Docker Compose environment variables: https://docs.docker.com/compose/how-tos/environment-variables/
- Python `os.environ`: https://docs.python.org/3.12/library/os.html#os.environ
