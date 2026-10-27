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
