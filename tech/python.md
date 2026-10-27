# Python 3.12

## What it is

Python is a programming language. You write instructions in text files that end in `.py`, and a program called the **interpreter** reads them and does what they say. This repository targets Python 3.12 (`requires-python = ">=3.12"` in `pyproject.toml`, and the Docker image is `python:3.12-slim-bookworm`). Your own laptop may run a newer one: the `Makefile` picks `python3.13` first, then `python3.12`, then `python3`.

A **module** is one `.py` file. A **package** is a folder of modules with an `__init__.py` file in it. A **library** is a package somebody else wrote that you install and `import`.

## Why this repository uses it

The lesson is about finding and fixing security weaknesses in a small web app. Python keeps the app short enough to read in an afternoon, and its standard library already contains the security basics the app needs: `secrets` for unguessable tokens, `hashlib` and `hmac` for digests and safe comparisons, `re` for allow-list validation, and `logging` for structured logs.

## Where it appears

| Path | What it does with Python |
| --- | --- |
| `src/notes_app/domain/` | Pure rules: validation, the access rule, the throttle rule, value objects. Standard library only. |
| `src/notes_app/application/` | Use cases (`AccountService`, `NoteService`, `SessionService`) and the `Protocol` ports they need. |
| `src/notes_app/infrastructure/` | Adapters: PostgreSQL, argon2, JSON logging, settings, clock. |
| `src/notes_app/interfaces/` | The Flask app, the gunicorn configuration, command-line programs (`health_cli.py`, `demo_cli.py`). |
| `tests/` | pytest tests at four levels: unit, integration, security, e2e. |
| `scripts/prove_controls.py` | A script that runs pytest again and again with one control removed each time. |

## How it works underneath

1. You run `python something.py` or a command like `gunicorn`. The operating system starts one **process**: the interpreter.
2. The interpreter **compiles** your text into **bytecode** (simple instructions) and runs it. Bytecode caches go into `__pycache__` folders. The Dockerfile sets `PYTHONDONTWRITEBYTECODE=1` so the container does not write them.
3. When code says `import x`, the interpreter looks for `x` in a list of folders (`sys.path`). The first match is loaded **once** and kept in memory. Later imports reuse it.
4. Every value is an **object** that lives in memory. Names point at objects. When no name points at an object any more, Python frees it.
5. **Type hints** like `user_id: int` are labels for humans and tools. Python does not enforce them while running. The tool `mypy` (see `tech/mypy.md`) checks them before you run.

## Walkthrough of this repository's use

### `from __future__ import annotations`

Almost every file starts with this line. It makes the interpreter store type hints as plain text instead of evaluating them at import time. That lets a hint refer to a class defined later in the file and avoids work at start-up.

### Dataclasses: value objects

```python
@dataclass(frozen=True, slots=True)
class User:
    """A registered user. ``password_hash`` is an encoded argon2id hash, never a password."""

    id: int
    username: str
    password_hash: str = ""
```

`@dataclass` writes `__init__`, `__repr__` and `__eq__` for you from the field list. `frozen=True` makes instances read-only after creation, so a `User` cannot change under you. `slots=True` stores the fields in a fixed layout instead of a per-object dictionary: less memory, and a typo like `user.nmae = ...` raises an error. `password_hash: str = ""` gives a field a default value.

`src/notes_app/domain/models.py` defines `User`, `Note`, `VisibleNote`, `Session` and `AuditEvent` this way. Because they are frozen, code that "changes" one must build a new one (the tests use `dataclasses.replace` for that).

### Enums

```python
class Access(IntEnum):
    NONE = 0
    READ = 1
    WRITE = 2
```

An **enum** is a fixed set of named values. `IntEnum` values are also integers, so `Access.WRITE >= Access.READ` is true. `NoteService._authorize` relies on that: `if access >= needed:`. `StrEnum` (used for `NoteRole` and `AuditAction`) members are also strings, so `AuditAction.LOGIN_SUCCESS.value` is `"login.success"` and can go straight into a database column.

### Protocols: ports without inheritance

```python
class UserRepository(Protocol):
    """Storage of users."""

    def add(self, username: str, password_hash: str) -> User:
        """Insert a user; raise ``UsernameTakenError`` when the username exists."""
```

A `Protocol` describes a shape: "anything with these methods". A class does not have to inherit from it. `PostgresUserRepository` has the same methods, so it counts as a `UserRepository`. Only `mypy` checks this. At run time nothing happens. `src/notes_app/application/ports.py` holds nine of these. This is how the application layer asks for a database without importing one.

### Keyword-only arguments

```python
def access_to_note(*, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
```

The bare `*` means every argument after it must be given by name: `access_to_note(owner_id=1, shared_with=set(), user_id=2)`. With three integers that are easy to mix up, this prevents swapping the owner and the user by accident.

### Union types and `None`

`User | None` means "a `User`, or `None`". Repository `by_username` returns `None` for "not found". `mypy` forces the caller to handle that case before using the user.

### Exceptions

```python
class InvalidInputError(NotesError):
    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason
```

`raise` stops normal flow; the nearest matching `except` catches it. `src/notes_app/domain/errors.py` gives every failure a name, and `interfaces/http/app.py` maps each name to exactly one HTTP status. `raise UsernameTakenError(username) from None` (in `postgres/users.py`) hides the lower-level database error so it does not leak into the traceback chain.

### Context managers

```python
@contextmanager
def connection(self) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with self._pool.connection(timeout=10) as connection:
        yield connection
```

`with` runs set-up, your block, then clean-up even if the block raised. `@contextmanager` turns a generator (a function with `yield`) into one. Here the clean-up is "give the connection back to the pool, and commit or roll back".

### Standard library pieces worth knowing

- `secrets.token_urlsafe(32)` (`infrastructure/clock.py`): 32 random bytes from the operating system's secure random source, encoded as 43 URL-safe characters. This is the session cookie value and the CSRF token. Do not use `random` for secrets: it is predictable.
- `hashlib.sha256(raw.encode()).hexdigest()` (`application/sessions.py`): a one-way fingerprint. The server stores the fingerprint of the cookie, never the cookie.
- `hmac.compare_digest(a, b)`: compares two byte strings in time that does not depend on where they first differ. Used for CSRF tokens.
- `re.compile(r"[a-z0-9_]{3,32}")` and `.fullmatch(...)` (`domain/validation.py`): an allow-list. `fullmatch` requires the whole string to match, not just a part.
- `datetime.now(UTC)`: a timezone-aware time. Mixing naive and aware times is a classic bug; the `DTZ` rules in ruff forbid naive ones.
- `logging` plus `json.dumps(..., separators=(",", ":"))` (`infrastructure/logging.py`): one compact JSON object per log line. A regular expression, `_SENSITIVE_KEY`, replaces the value of any field whose name contains `password`, `token`, `cookie`, `csrf`, `session` and similar, with `[redacted]`.
- `os.environ` (via `Mapping[str, str]` in `Settings.from_environment`): configuration comes from environment variables. The function takes the mapping as an argument so tests can pass their own dictionary.
- `urllib.request` and `http.client` appear in the two command-line programs that talk to a running server.

### Command-line entry points

`pyproject.toml` declares:

```toml
[project.scripts]
notes-app-health = "notes_app.interfaces.health_cli:main"
notes-app-demo = "notes_app.interfaces.demo_cli:main"
```

When the package is installed, the installer creates programs `.venv/bin/notes-app-health` and `.venv/bin/notes-app-demo` that call those functions. `health_cli.main()` returns an integer and the last two lines, `if __name__ == "__main__": sys.exit(main())`, turn that into the process **exit code** (0 means success; anything else means failure; Docker's health check and `make health` read it).

## Try it yourself

Run these from the repository root after `make install`.

1. See which interpreter the project uses:
   ```bash
   .venv/bin/python --version
   ```
   Expect `Python 3.12.x` or newer (the maintainer's machine printed `Python 3.13.12`).
2. Try the throttle rule, a pure function with no database:
   ```bash
   .venv/bin/python -c "
   from datetime import datetime, timedelta, UTC
   from notes_app.domain.throttle import retry_after_seconds
   now = datetime.now(UTC)
   print(retry_after_seconds([now]*5, now=now, max_failures=5, window=timedelta(minutes=15)))"
   ```
   Expect `901`: five failures just now, so the next attempt waits the whole 900-second window plus one second.
3. Watch a frozen dataclass refuse a change:
   ```bash
   .venv/bin/python -c "
   from notes_app.domain.models import User
   u = User(1, 'alice'); u.username = 'bob'"
   ```
   Expect `FrozenInstanceError: cannot assign to field 'username'`.
4. Make a token like the app's:
   ```bash
   .venv/bin/python -c "import secrets; t = secrets.token_urlsafe(32); print(len(t), t)"
   ```
   Expect `43` and a random-looking string.

## Mistakes people make

- Using `random` instead of `secrets` for tokens. This repository uses `secrets` only (`SecretsTokenGenerator`).
- Comparing secrets with `==`. A normal comparison can stop at the first different character, and the time it takes can leak how many characters matched. `SessionService.csrf_valid` uses `hmac.compare_digest`.
- Mutable default arguments (`def f(x=[])`). The code uses immutable defaults such as `()` and `""`.
- Naive datetimes (no timezone). The clock returns `datetime.now(UTC)` and the database columns are `timestamptz`.
- Catching `Exception` everywhere. The code catches specific classes (`VerifyMismatchError`, `UniqueViolation`) and has one deliberate catch-all in the Flask error handlers, which logs the stack trace and returns a generic 500.
- `assert` for validating input. Python can run with assertions switched off (`-O`), so the repository uses `assert` only for "this cannot be `None`" after a query that always returns a row, and ruff's `S101` rule makes each use carry an explanatory `noqa` comment.

## Check yourself

1. What does `frozen=True` do on a dataclass, and why do the value objects use it?
   *It makes instances read-only after creation, so a value cannot be changed by accident after the service checked it.*
2. Why does `access_to_note` have a bare `*` in its parameter list?
   *Every following argument must be passed by name, so the owner id and user id cannot be swapped silently.*
3. What is a `Protocol`, and who checks that a class satisfies one?
   *A description of required methods; `mypy` checks it, Python does not at run time.*
4. Why does the server store `hashlib.sha256(token)` and not the token itself?
   *A leaked database copy then contains no value that can be put in a cookie.*
5. What does `if __name__ == "__main__": sys.exit(main())` accomplish?
   *It runs `main()` only when the file is executed directly and passes its return value to the operating system as the exit code.*

## Further reading

- Python 3.12 documentation: https://docs.python.org/3.12/
- `dataclasses`: https://docs.python.org/3.12/library/dataclasses.html
- `typing.Protocol`: https://docs.python.org/3.12/library/typing.html#typing.Protocol
- `secrets`: https://docs.python.org/3.12/library/secrets.html
- `hmac.compare_digest`: https://docs.python.org/3.12/library/hmac.html#hmac.compare_digest
