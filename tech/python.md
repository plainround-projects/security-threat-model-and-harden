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

### Ideas you need first

If you have never programmed, read this list once. Each idea is used in the walkthrough below.

- **A program and a file.** A program is a list of instructions. Python programs live in plain text files whose names end in `.py`. You can open them in any text editor.
- **A directory (folder) and a path.** A directory holds files and other directories. A **path** is the address of a file, such as `src/notes_app/domain/access.py`: start in `src`, go into `notes_app`, then `domain`, then the file `access.py`.
- **A variable.** A name that points at a value: `limit = 5` makes the name `limit` point at the number 5. Later code can say `limit` and get 5.
- **A value and its type.** Every value has a kind: whole numbers (`int`), text (`str`), true or false (`bool`), "nothing" (`None`), and containers. A **list** is an ordered row of values (`[1, 2, 3]`). A **tuple** is a list that cannot be changed (`(1, 2)`). A **set** is a bag of distinct values with no order (`{1, 2}`); a **frozenset** is a set that cannot be changed. A **dict** (dictionary) maps keys to values (`{"name": "alice"}`).
- **A function.** A named, reusable piece of code: `def add(a, b): return a + b`. You **call** it with `add(1, 2)`. The values you pass are **arguments**; the names inside the function are **parameters**. `return` hands a result back.
- **A class and an object.** A class is a blueprint; an **object** (an instance) is one thing built from it. A class bundles data (**attributes**) and functions (**methods**). Inside a method, the first parameter, `self`, is the object itself. `__init__` is the method Python runs when an object is created. A class can **inherit** from another (`class A(B)`): it gets B's methods and may add more. `super()` means "the parent class".
- **A module, a package and `import`.** A module is one `.py` file; a package is a directory of modules with an `__init__.py` file. `import x` or `from x import y` makes code from another module available. The first time a module is imported, Python runs it once and remembers it.
- **An exception.** A signal that something went wrong. `raise SomeError("message")` stops the normal flow. `try: ... except SomeError: ...` catches it and runs other code instead. `finally:` runs in every case. An exception that nothing catches ends the program with a **traceback** (a list of the calls that led to the error).
- **A decorator.** A line starting with `@` above a function or class, such as `@dataclass`. It wraps or registers the thing below it. `@app.get("/healthz")` registers the function below as the handler for that web address.
- **A type hint.** Labels such as `def f(user_id: int) -> str`. They say what kinds of values go in and out. Python itself ignores them when the program runs; a checker called mypy reads them (`tech/mypy.md`).
- **An f-string.** Text with values inserted: `f"user {name}"` becomes `user alice` when `name` is `"alice"`.
- **A comprehension.** A compact way to build a list, set or dict from another: `[x * 2 for x in numbers]` is "for each x in numbers, take x times 2".
- **A generator and `yield`.** A function that hands back values one at a time with `yield`, pausing between them.
- **A context manager and `with`.** `with something as name:` runs set-up code, then your indented block, then clean-up code, even if the block raises. Files, locks and database connections use it.
- **A process.** A running copy of a program. The operating system gives each process its own memory. Starting `python script.py` makes one process.
- **A thread.** A path of execution inside one process. Several threads share that process's memory and can run at the same time.
- **Standard output, standard error, exit code.** `print(...)` writes to standard output (stdout), the normal output stream. A second stream, standard error (stderr), is for problems and logs. When a process ends it returns a number, the **exit code**: 0 means success, anything else means failure.
- **An environment variable.** A named piece of text that the operating system gives to every process it starts, such as `PATH` or `HOME`. Programs read them with `os.environ`. The values are always text.
- **Standard library.** The large set of modules that ship with Python itself (`json`, `hashlib`, `secrets`, `re`, `logging`...). They need no installation. Anything else is a **third-party library**, installed with a package manager (`tech/uv-and-lock-files.md`).

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
- `logging` plus `json.dumps(..., separators=(",", ":"))` (`infrastructure/logging.py`): one compact JSON object per log line. A regular expression, `_SENSITIVE_KEY`, replaces the value of any field whose name contains `pass`, `passwd`, `password`, `secret`, `token`, `cookie`, `authorization`, `csrf`, `session` or `api_key` (also written `api-key`), with `[redacted]`.
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

### Every module, one by one

The package is `src/notes_app/`, in four layers. A **layer** is a group of modules with one job. The rule (enforced by `tech/import-linter.md`) is that a layer may use the ones below it and never the ones above: `interfaces` (talks to the outside world) uses `infrastructure` (database, hashing, logging), which uses `application` (the use cases), which uses `domain` (the rules). This section walks every module, bottom layer first. The `__init__.py` file of each folder holds only a one-line description in a **docstring** (a text string placed first in a module, class or function to document it); its presence is what makes the folder a package.

#### Layer 1: `domain/`, pure rules

**`domain/access.py`** decides who may do what with a note.

```python
class Access(IntEnum):
    NONE = 0
    READ = 1
    WRITE = 2
```
An **enum** is a fixed list of named values. `IntEnum` makes each name also a whole number, so `Access.WRITE >= Access.READ` is true. The numbers encode "each level includes the one below".

```python
def access_to_note(*, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
    if user_id == owner_id:
        return Access.WRITE
    if user_id in shared_with:
        return Access.READ
    return Access.NONE
```
The bare `*` means every parameter after it must be given by name, so the three integer ids cannot be mixed up by position. `Collection[int]` means "any group of integers you can ask `in` about". The three lines are the whole authorization rule: the owner may write, someone the note is shared with may read, everyone else gets nothing. `from __future__ import annotations` at the top (every module has it) makes the type hints text instead of live values, so a hint may name something defined later.

**`domain/errors.py`** names every failure on purpose.

```python
class NotesError(Exception):
    """Base class of every error the application raises on purpose."""
```
Every other error inherits from it, so code can catch "any intended failure" with one `except NotesError`. The classes are: `InvalidInputError(field, reason)` (stores both so the web layer can answer with them); `UsernameTakenError`; `AuthenticationFailedError` (its message never says which half of the sign-in was wrong); `LoginThrottledError(retry_after_seconds)` (stores the wait); `NoteNotFoundError` (raised both when a note does not exist and when you may not know it exists, so a response never confirms which ids exist); `NoteForbiddenError` (you can see the note but may not do this); `CsrfRejectedError`. `super().__init__(f"{field}: {reason}")` runs the parent's setup with a built message; `self.field = field` keeps the pieces as attributes.

**`domain/models.py`** holds the plain data the program passes around.

```python
@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    password_hash: str = ""
```
`@dataclass` writes `__init__`, `__repr__` (the text shown when you print the object) and `__eq__` (comparison) from the field list. `frozen=True` forbids changing a field after creation; `slots=True` stores fields in a fixed compact layout. `password_hash: str = ""` gives a default. The classes: `User`; `Note` (id, owner, title, content, two timestamps); `NoteRole` (a `StrEnum`: `"owner"` or `"reader"`, which is both an enum member and a string); `VisibleNote` (a `Note` plus the requester's role and the owner's name, what the notes page lists); `Session` (the server-side session: hashed token, user id or `None`, CSRF token, three timestamps); `AuditAction` (a `StrEnum` of nine event names such as `"login.success"`); `AuditEvent` (action, outcome, user id, address, and `detail`, a tuple of pairs of text, never credentials). `int | None` means "a whole number or nothing".

**`domain/throttle.py`** is the sign-in rate rule as one pure function.

```python
def retry_after_seconds(failures, *, now, max_failures, window) -> int | None:
    live = sorted(moment for moment in failures if moment > now - window)
    if len(live) < max_failures:
        return None
    blocking = live[len(live) - max_failures]
    return max(int((blocking + window - now).total_seconds()) + 1, 1)
```
`failures` is a collection of times of earlier failed sign-ins. The first line is a **generator expression** inside `sorted(...)`: keep only failures newer than `now - window` (a `timedelta`, a length of time), sorted oldest first. If fewer than `max_failures` remain, return `None` (allowed). Otherwise the blocking failure is the one that will be the first to leave the window once the count must drop below the limit: `live[len(live) - max_failures]`. The wait is the time until it ages out, rounded down to whole seconds, plus one, and never less than one. Because it takes the times as arguments and touches no database or clock, five unit tests can pin its behavior exactly.

**`domain/validation.py`** is the input allow-list.

```python
USERNAME_PATTERN = re.compile(r"[a-z0-9_]{3,32}")
```
A **regular expression** (regex) describes a text pattern: here 3 to 32 characters, each a lower-case letter, digit or underscore. `re.compile` prepares it once.

- `validate_username(raw)`: `raw.strip().lower()` removes surrounding spaces and lower-cases; `USERNAME_PATTERN.fullmatch(username)` requires the **whole** string to match (not just a part); otherwise it raises `InvalidInputError("username", ...)`. It returns the canonical form.
- `validate_password(raw)`: only the length is checked, 12 to 128 characters (length is the rule that matters; the upper bound stops someone making the server hash a huge value).
- `validate_note_title(raw)`: stripped, 1 to 120 characters, and no NUL, newline or carriage return (`"\x00"`, `"\n"`, `"\r"` are escape codes for those control characters).
- `validate_note_content(raw)`: at most 10,000 characters and no NUL byte (PostgreSQL cannot store one). Markup such as `<script>` is **allowed**, because the output side encodes it (`tech/jinja2-templates.md`).

#### Layer 2: `application/`, the use cases

**`application/ports.py`** lists what the use cases need from outside, as `Protocol`s. A `Protocol` is a description of required methods: any class with those methods qualifies, no inheritance needed (a type checker verifies it). The nine ports and their methods: `UserRepository` (`add`, `by_username`, `by_id`, `update_password_hash`); `NoteRepository` (`add`, `get`, `shared_with`, `update`, `delete`, `share`, `list_visible`); `SessionRepository` (`add`, `get`, `touch`, `delete`, `purge_expired`); `AuditLog` (`record`); `PasswordHasher` (`hash`, `verify`, `needs_rehash`, `spend_equal_effort`); `LoginThrottle` (`check`, `record_failure`, `reset`); `AccessPolicy` (`access`); `Clock` (`now`); `TokenGenerator` (`new_token`). Each method has only a docstring as its body (that is legal Python) because a protocol states the shape, not the work.

**`application/policy.py`** is `OwnerOrSharedPolicy`: one method, `access`, that calls the domain function. It is the production implementation of the `AccessPolicy` port.

**`application/accounts.py`** is `AccountService`: sign-up and sign-in.

- `__init__` stores five collaborators (users, hasher, throttle, audit, clock) in private attributes (a leading underscore marks "internal"). This is **dependency injection**: the service is handed what it needs instead of creating it, so tests can hand it fakes.
- `register(username, password, ip)`: validates, hashes the password with a fresh salt, stores the user, writes a `SIGNUP` audit event, returns the user.
- `authenticate(username, password, ip)`, step by step: build the throttle key `f"{ip}|{username.strip().lower()}"`; ask the throttle (`check`), and on `LoginThrottledError` audit it and re-`raise`; look the user up with `_find`; if the user is missing or `verify` is false, then, **for a missing user only**, call `spend_equal_effort` (a dummy hash, so the response time does not reveal which usernames exist), record the failure, audit it, and raise `AuthenticationFailedError("invalid username or password")` (the same message either way); on success `reset` the throttle key, re-hash the password if the stored hash used weaker settings (`needs_rehash`), audit `LOGIN_SUCCESS`, return the user.
- `get_user(user_id)` fetches the user for the page header.
- `_find(username)` validates the name and returns `None` for an invalid or unknown name (it swallows `InvalidInputError` on purpose: a malformed name is just "no such user").

**`application/notes.py`** is `NoteService`: every note operation, each through one authorization check.

- `create`, `list_visible`: validate and store, or list.
- `get(user_id, note_id, ip)`: authorizes `Access.READ`.
- `update(...)`: authorizes `Access.WRITE`, validates only the fields supplied (`None` means "leave as is"), stores.
- `delete(...)`: authorizes `WRITE`, deletes, audits `NOTE_DELETED`.
- `share(...)`: authorizes `WRITE`, looks the target user up, refuses an unknown user or sharing with yourself, stores the share, audits `NOTE_SHARED`.
- `_authorize(user_id, note_id, needed, ip)`: fetches the note (missing means `NoteNotFoundError`), fetches its share list **fresh from the database**, asks the policy, and if the level is enough returns the note. Otherwise it writes a `NOTE_ACCESS_DENIED` audit event with the note id and a reason (`no_access` or `read_only`) and raises `NoteNotFoundError` when the user has no access at all (so ids cannot be probed) and `NoteForbiddenError` when they can read but not write.

**`application/sessions.py`** is the server-side session logic.

- `SessionPolicy` and `IssuedSession` are frozen dataclasses (three lifetimes in seconds; a new session plus the raw cookie value).
- `hash_token(raw)`: `hashlib.sha256(raw.encode()).hexdigest()`. `.encode()` turns text into bytes; SHA-256 is a one-way fingerprint function; `.hexdigest()` writes it as 64 hexadecimal characters.
- `start_anonymous()`: a session with no user, so the sign-in form carries a CSRF token.
- `sign_in(previous_raw_token, user_id)`: delete the earlier session (this defeats **session fixation**, where an attacker plants a known id before sign-in), purge expired sessions, issue a new one.
- `resolve(raw_token)`: hash the cookie, fetch, and delete and return `None` if it is past `expires_at` or (for signed-in sessions) idle longer than the idle limit; touch `last_seen_at` at most once a minute (`TOUCH_INTERVAL`) to avoid a database write per request.
- `sign_out`, `csrf_valid` (uses `hmac.compare_digest`, which compares two byte strings in time that does not reveal where they first differ), and `_issue`, which creates the raw token and a second token for CSRF, builds the `Session`, stores it.

#### Layer 3: `infrastructure/`, the adapters

**`infrastructure/clock.py`**: `SystemClock.now()` returns `datetime.now(UTC)`; `SecretsTokenGenerator.new_token()` returns `secrets.token_urlsafe(32)` (32 random bytes from the operating system, 43 URL-safe characters).

**`infrastructure/argon2_hasher.py`**: `Argon2PasswordHasher` wraps the `argon2` library (`tech/argon2.md`). `__init__` builds the library hasher with the three cost settings and makes one **dummy hash** of a throwaway string. `hash`, `verify` (catches three library exceptions and returns `False`, so a malformed stored value simply never matches), `needs_rehash`, and `spend_equal_effort` (verify against the dummy and discard).

**`infrastructure/logging.py`**: `redact(fields)` returns a copy of a dictionary where every key matching the regex `pass|passwd|password|secret|token|cookie|authorization|csrf|session|api_key` (case-insensitive) has its value replaced by `"[redacted]"`. `JsonFormatter.format(record)` builds a dictionary (time as ISO text with milliseconds, level, logger name, message) and adds every **extra** field the log call supplied (the code finds them by comparing the record's attributes with `_RESERVED`, the set of attribute names a plain `LogRecord` already has), redacted; an exception is added as text; the dictionary is written with `json.dumps(..., separators=(",", ":"))`. `configure_logging(level)` replaces the root logger's handlers with one that writes to standard error using this formatter.

**`infrastructure/settings.py`**: reads all configuration from environment variables once, at start-up (`tech/dotenv.md` lists every variable). `ConfigError` is the failure type. `_read_int` converts a variable to a whole number with a minimum, raising a clear error for text that is not a number. `Weaknesses` is a frozen dataclass of seven booleans; `from_environment` builds it with a **dictionary comprehension** over `fields(cls)` reading `UNSAFE_<NAME>`; `enabled()` lists the ones on. `DatabaseSettings` holds connection details (`password: str = field(repr=False)` hides it from printouts) and `conninfo()` builds the connection string. `Settings.from_environment` validates `APP_ENV`, requires `NOTES_DB_PASSWORD`, reads every value, then `_validate` refuses: any weakness outside `APP_ENV=test`; Argon2 settings below the OWASP minimum outside test; a pool minimum above its maximum; an anonymous-session lifetime above the absolute one.

**`infrastructure/postgres/database.py`**: `Database` owns the connection pool (`tech/psycopg.md`): `open`, `close`, `connection()` (a context manager yielding a connection in a transaction), `ping`.

**`infrastructure/postgres/users.py`, `notes.py`, `sessions.py`, `throttle.py`, `audit.py`**: one repository each, implementing the matching port with constant SQL statements and `%s` placeholders (statement by statement in `tech/psycopg.md` and `tech/sql.md`). Points of Python: `users.add` catches `UniqueViolation` and re-raises `UsernameTakenError ... from None` (hide the lower-level error); `notes.to_note(row)` converts a database row (a tuple) into a `Note`, with `int(str(row[0]))` because the row's values have the vague type `object`; `_timestamp` uses `assert isinstance(value, datetime)` to tell the type checker the column is a datetime (`# noqa: S101` explains the waived lint rule); `throttle` stores only a SHA-256 of `ip|username` (`_key_hash`), so the table holds neither; `audit.record` first writes a log line (`_log.info("audit", extra={...})`) and then inserts a row inside `try/except psycopg.Error`, logging loudly rather than failing the user's request if the table is unavailable.

**`infrastructure/weaknesses/`** holds three deliberately bad replacements used only by `make prove` with `APP_ENV=test`: `UnsaltedSha256Hasher` (a bare SHA-256 as the "password hash"), `ConcatenatedNoteRepository` (builds the INSERT by joining strings), `AllowEverythingPolicy` (`access` always returns `Access.WRITE`). Each exists so a test can fail without the matching control.

#### Layer 4: `interfaces/`, the outside world

**`interfaces/composition.py`**: the one place that knows which adapter implements which port. `Container` is a frozen dataclass of the wired objects. `build_container(settings)` creates the database, clock, audit log, repositories and hasher, swapping in a weakness when its flag is on (`Argon2PasswordHasher(...) if not weak.weak_password_hash else UnsaltedSha256Hasher()`, written as a conditional expression `a if condition else b`), and returns the three services.

**`interfaces/wsgi.py`**: `build_app()` reads settings from `os.environ`, configures logging, builds the container, opens the pool, remembers the container in a module-level list `_containers`, logs `started` (and a warning if any weakness is on), and returns the Flask app. `close_all()` pops each container and closes its pool.

**`interfaces/gunicorn_conf.py`**: plain assignments that gunicorn reads (`tech/gunicorn.md`), plus `worker_exit`, which imports `close_all` inside the function and calls it.

**`interfaces/health_cli.py`**: `main()` builds the URL `http://127.0.0.1:<port>/readyz`, opens it with `urllib.request.urlopen(url, timeout=3)` inside `with`, treats status 200 as healthy, prints `healthy` or `unhealthy: <error>` (errors to standard error), and returns 0 or 1. The last two lines, `if __name__ == "__main__": sys.exit(main())`, run it only when executed directly and turn the return value into the process exit code.

**`interfaces/http/security.py`**: constants (the cookie name, header table, CSP string), the frozen `CookieAttributes` dataclass, `HARDENED_COOKIE` and `WEAK_COOKIE`, `apply_security_headers`, `set_session_cookie`, `clear_session_cookie` (`tech/http-cookies-csrf-and-headers.md`).

**`interfaces/http/app.py`**: the Flask application (`tech/flask.md`). Python features used: nested functions registered with decorators inside `create_app`; `g.get("x")` with a default; a dictionary mapping error classes to lambdas (`lambda error: respond(...)` is a one-line anonymous function); `_Unauthenticated` as a private exception class used for control flow; `isinstance(value, str)` checks on input from JSON.

**`interfaces/demo_cli.py`**: the lesson's scenario as a program.
- `Step` and `Reply` are frozen dataclasses; `Reply.json()` parses the body and returns `{}` when it is not an object.
- `Browser` is a tiny HTTP client with one cookie. `request(method, path, form=..., body=..., headers=...)`: builds the payload (`urlencode(form)` for a form, `json.dumps(body)` for JSON), adds the session cookie by hand (a plain `http://` client rightly will not return a `Secure` cookie), opens `http.client.HTTPConnection`, sends, reads the status, headers and body, closes in `finally`, and then updates the stored cookie from any `Set-Cookie` (a `Max-Age=0` means the server cleared it). `csrf_token()` fetches `/login` and finds the hidden field with a regex. `register(prefix)` makes a username and a random password with `secrets`, signs up, signs in. `api(...)` sends a JSON request with the CSRF header.
- `_cookie_flags(set_cookies)` checks the session cookie has the four attributes and an opaque value of at least 40 characters with fewer than two dots (a JWT has two).
- `run_scenario(host, port)` runs eight checks with two browsers, Alice and Bob: readiness; cookie flags; security headers; hostile content stored and rendered as text; Bob gets 404 for read, update and delete of Alice's note; a request without the CSRF token and with a wrong one gets 403; six wrong passwords give five `401`s then a `429`; after sign-out the old cookie gives `401`. `check(name, passed, detail)` is a nested function that appends a `Step`.
- `main` parses `--host` and `--port` with `argparse`, prints one line per step (`f"{number:>2}. PASS ..."`; `:>2` right-aligns in two characters), and returns 1 if any step failed.

#### Scripts

**`scripts/prove_controls.py`** is the "remove each control" proof (`tech/stride-threat-modeling.md`). `GUARDS` is a dictionary from a weakness name to the tuple of test ids that must fail when it is on. `run_pytest(node_ids, weakness)` runs `python -m pytest ... -rA --tb=no` as a **subprocess** (a child process) with a copy of the environment minus any `UNSAFE_*` variables, plus `APP_ENV=test` and the chosen weakness, captures the output, and reads lines starting with `PASSED`, `FAILED` or `ERROR` into a dictionary of results. `main` first runs every guard with no weakness (all must pass), then each weakness and prints `FAILS without the control (proven)` or `STILL PASSES (not proven)`, and exits 1 if any is unproven.

### Line by line: `src/notes_app/__init__.py`

A file named `__init__.py` marks a folder as a Python **package**, a folder of modules that can be imported by name. Whatever it contains runs the first time the package is imported.

```python
"""A notes app, threat-modeled with STRIDE and hardened one control at a time."""

__version__ = "0.1.0"
```

A **docstring** (text in triple quotes at the top of a file; Python stores it and tools can show it) saying what the package is, and `__version__`, a plain variable holding the version text by convention.

### Line by line: `src/notes_app/application/__init__.py`

```python
"""Use cases of the notes app and the ports they need. Depends on the domain only."""
```

The marker file of the `application` layer: the use cases and the **ports** they need (descriptions of what the outside world must provide). It may import only the domain layer, and import-linter fails the build if that ever changes.

### Line by line: `src/notes_app/domain/__init__.py`

```python
"""Rules and value objects of the notes app. Depends on nothing outside the standard library."""
```

The marker of the `domain` layer: the rules and plain data of the application, using only Python's standard library.

### Line by line: `src/notes_app/infrastructure/__init__.py`

```python
"""Adapters: PostgreSQL, argon2, logging, settings, the clock. Depends on the application and domain layers."""
```

The marker of the `infrastructure` layer: the adapters for PostgreSQL, argon2, logging, settings and the clock.

### Line by line: `src/notes_app/infrastructure/postgres/__init__.py`

```python
"""PostgreSQL adapters. Every statement binds its values as parameters; none builds SQL from input."""
```

The marker of the PostgreSQL adapter package. Its docstring states the rule: every statement binds its values as parameters and none builds SQL from input.

### Line by line: `src/notes_app/infrastructure/weaknesses/__init__.py`

```python
"""Deliberately weakened variants of controls, one per control, switched on only by ``UNSAFE_*`` settings and only
under ``APP_ENV=test``. Tests run the same assertions with a weakness on and watch them fail, which proves each
control. Nothing in here is reachable in a normal run."""
```

The marker of the package of deliberately weakened controls. The docstring explains the idea: one weakened variant per control, switched on only by `UNSAFE_*` settings and only when `APP_ENV=test`. Tests run the same assertions with a weakness switched on and watch them fail, which proves the control is what makes them pass. Nothing here is reachable in a normal run.

### Line by line: `src/notes_app/interfaces/__init__.py`

```python
"""Entry points: the HTTP application, the WSGI and gunicorn wiring, and the command-line programs. Nothing depends
on this layer."""
```

The marker of the `interfaces` layer: the HTTP application, the WSGI and gunicorn wiring and the command-line programs. Nothing depends on this layer.

### Line by line: `src/notes_app/interfaces/http/__init__.py`

```python
"""The Flask application: routes, templates, session cookie, CSRF check and security headers."""
```

The marker of the `http` package: routes, templates, the session cookie, the CSRF check and the security headers.

### Line by line: `src/notes_app/domain/access.py`

```python
"""The authorization rule for notes, as a pure function so it can be tested without a database."""
```

The docstring: the authorization rule for notes as a **pure function** (it reads only its arguments and returns a value, with no database or file), so it can be tested without a database.

```python
from __future__ import annotations
```

`from __future__ import annotations` keeps type hints as text instead of evaluating them when the file loads.

```python
from collections.abc import Collection
from enum import IntEnum
```

`Collection` is the type name for "anything you can ask `in` and `len` of" (a set, a list). `IntEnum` is an enumeration whose members are also integers, so they can be compared with `<` and `>=`.

```python
class Access(IntEnum):
    """What a user may do with one note. Ordered: each level includes the one below."""

    NONE = 0
    READ = 1
    WRITE = 2
```

`Access` is a closed list of three levels: `NONE` (0), `READ` (1) and `WRITE` (2). The docstring notes they are ordered, each including the one below, so `access >= Access.READ` means "may at least read".

```python
def access_to_note(*, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
    """The owner may read and write; a user the note is shared with may read; everyone else gets nothing."""
    if user_id == owner_id:
        return Access.WRITE
    if user_id in shared_with:
        return Access.READ
    return Access.NONE
```

`access_to_note` takes keyword-only arguments (the `*` forces names at the call, so the owner id and the user id cannot be swapped by mistake). The owner gets `WRITE`; a user in the `shared_with` collection gets `READ`; everyone else gets `NONE`. This is the whole authorization rule of the application, in seven lines.

### Line by line: `src/notes_app/domain/errors.py`

```python
"""Named errors. Each one maps to exactly one HTTP outcome at the interface layer."""
```

The docstring: each named error maps to exactly one HTTP outcome in the interface layer.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
class NotesError(Exception):
    """Base class of every error the application raises on purpose."""
```

`NotesError` is the base class of every error raised on purpose. One `except NotesError` catches all of them, while a real bug (any other error type) stays visible.

```python
class InvalidInputError(NotesError):
    """A value failed validation at a boundary."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason
```

`InvalidInputError` is for a value that failed validation. It keeps the `field` and the `reason` as attributes; `super().__init__(...)` calls the parent constructor with the combined message `"field: reason"`.

```python
class UsernameTakenError(NotesError):
    """Sign-up asked for a username that already exists."""
```

`UsernameTakenError`: sign-up asked for a username that exists.

```python
class AuthenticationFailedError(NotesError):
    """Sign-in failed. The message never says whether the username or the password was wrong."""
```

`AuthenticationFailedError`: sign-in failed. The docstring states the rule that its message never says whether the username or the password was wrong, so an attacker cannot learn which usernames exist.

```python
class LoginThrottledError(NotesError):
    """Too many failed sign-ins for this client and username in the window."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"too many failed sign-ins, retry in {retry_after_seconds} seconds")
        self.retry_after_seconds = retry_after_seconds
```

`LoginThrottledError`: too many failed sign-ins. It carries `retry_after_seconds`, which the web layer puts in the `Retry-After` header.

```python
class NoteNotFoundError(NotesError):
    """The note does not exist, or the caller may not know that it does.

    Both cases raise this one error so a response never confirms which ids exist.
    """
```

`NoteNotFoundError`: the note does not exist, or the caller may not know that it does. Using one error for both cases means a response never confirms which ids exist.

```python
class NoteForbiddenError(NotesError):
    """The caller can see the note but lacks the right for this action (a reader trying to edit)."""
```

`NoteForbiddenError`: the caller can see the note but lacks the right for this action, for example a reader trying to edit.

```python
class CsrfRejectedError(NotesError):
    """A state-changing request arrived without the session's CSRF token."""
```

`CsrfRejectedError`: a state-changing request arrived without the session's CSRF token (`tech/http-cookies-csrf-and-headers.md`).

### Line by line: `src/notes_app/domain/models.py`

```python
"""Immutable value objects of the notes app."""
```

The docstring: immutable value objects, meaning records that cannot change after creation.

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
```

Imports: `dataclass` (writes the repetitive methods of a data-holding class), `datetime` (a date and time) and `StrEnum` (an enumeration whose members behave like strings).

```python
@dataclass(frozen=True, slots=True)
class User:
    """A registered user. ``password_hash`` is an encoded argon2id hash, never a password."""

    id: int
    username: str
    password_hash: str = ""
```

`User` is a frozen dataclass (`frozen=True` makes fields read-only after creation; `slots=True` stores them in a fixed compact structure). The password field holds an encoded argon2id hash, never a password; its default is the empty text.

```python
@dataclass(frozen=True, slots=True)
class Note:
    """A note and its owner."""

    id: int
    owner_id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
```

`Note` has an id, the owner's id, a title and content, and two timestamps.

```python
class NoteRole(StrEnum):
    """How the requesting user relates to a note they can see."""

    OWNER = "owner"
    READER = "reader"
```

`NoteRole` has two members: `OWNER` and `READER`, how the requester relates to a note they can see.

```python
@dataclass(frozen=True, slots=True)
class VisibleNote:
    """A note together with the requester's role, as listed on the notes page."""

    note: Note
    role: NoteRole
    owner_username: str
```

`VisibleNote` pairs a note with the requester's role and the owner's username, as listed on the notes page.

```python
@dataclass(frozen=True, slots=True)
class Session:
    """A server-side session. ``user_id`` is ``None`` until sign-in (an anonymous session carries the CSRF token
    of the sign-in form)."""

    token_hash: str
    user_id: int | None
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
```

`Session` is a server-side session. Only the hash of the cookie value is stored (`token_hash`), so a stolen database does not reveal usable cookies. `user_id` is `None` until sign-in: an anonymous session exists so the sign-in form can carry a CSRF token. The three times are creation, last activity and absolute expiry.

```python
class AuditAction(StrEnum):
    """Security events worth an audit row."""

    SIGNUP = "signup"
    LOGIN_SUCCESS = "login.success"
    LOGIN_FAILURE = "login.failure"
    LOGIN_THROTTLED = "login.throttled"
    LOGOUT = "logout"
    NOTE_ACCESS_DENIED = "note.access_denied"
    NOTE_SHARED = "note.shared"
    NOTE_DELETED = "note.deleted"
    CSRF_REJECTED = "csrf.rejected"
```

`AuditAction` lists the nine security events that get an audit row: sign-up, login success, failure and throttled, logout, note access denied, note shared, note deleted, and CSRF rejected. The text value (such as `login.failure`) is what is stored.

```python
@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One security-relevant event. ``detail`` holds ids and reasons only, never credentials or free text."""

    action: AuditAction
    outcome: str
    user_id: int | None
    ip: str
    detail: tuple[tuple[str, str], ...] = ()
```

`AuditEvent` is one event: the action, an outcome text, the user id (or `None`), the client's IP and a `detail` tuple of key-value pairs. The docstring rule: detail holds ids and reasons only, never credentials or free text. Pairs are used instead of a dictionary because a frozen dataclass should hold only immutable values.

### Line by line: `src/notes_app/domain/throttle.py`

```python
"""The sliding-window rule behind the sign-in throttle, as a pure function."""
```

The docstring: the **sliding-window** rule behind the sign-in throttle. A sliding window counts only the events of the last N minutes, so old failures stop counting by themselves.

```python
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
```

Imports: `Iterable` (anything you can loop over) and `datetime` with `timedelta` (a length of time).

```python
def retry_after_seconds(
    failures: Iterable[datetime], *, now: datetime, max_failures: int, window: timedelta
) -> int | None:
```

The function takes the earlier failure times, and keyword-only `now`, `max_failures` and `window`. It returns the seconds to wait, or `None` when the key is under its limit.

```python
    """Seconds until another attempt is allowed, or ``None`` when the key is under its limit.

    ``failures`` are the timestamps of earlier failed sign-ins. Only those inside the window count; once
    ``max_failures`` of them are inside it, the next attempt waits until the oldest of those ages out.
    """
```

The docstring spells out the rule: only failures inside the window count; once `max_failures` of them are inside it, the next attempt waits until the oldest of those ages out.

```python
    live = sorted(moment for moment in failures if moment > now - window)
```

`live` is the sorted list of failure times that are later than `now - window` (still inside the window).

```python
    if len(live) < max_failures:
        return None
```

If fewer than the limit are live, the answer is `None`: no waiting.

```python
    blocking = live[len(live) - max_failures]
    return max(int((blocking + window - now).total_seconds()) + 1, 1)
```

`blocking` is the failure that must age out: the one `max_failures` places from the end of the sorted list. The wait is the time until that failure plus the window, converted to whole seconds, plus one second so the wait never ends a moment too early, and never less than 1. For example with a limit of 5 and a window of 15 minutes, five failures at times t1 to t5 block until t1 plus 15 minutes.

### Line by line: `src/notes_app/domain/validation.py`

```python
"""Input validation at the boundary: allow-lists and length limits, no escaping (that is the output's job)."""
```

The docstring: input validation at the boundary with **allow-lists** (state what is allowed, refuse the rest) and length limits. It does not escape anything; escaping is the output's job.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import re

from notes_app.domain.errors import InvalidInputError
```

`re` is Python's regular-expression module, and `InvalidInputError` comes from the same layer.

```python
USERNAME_PATTERN = re.compile(r"[a-z0-9_]{3,32}")
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
TITLE_MAX_LENGTH = 120
CONTENT_MAX_LENGTH = 10_000
```

The limits as named constants. `USERNAME_PATTERN` is a **regular expression** (a text pattern): `[a-z0-9_]` means one lower-case letter, digit or underscore and `{3,32}` means 3 to 32 of them. Passwords are 12 to 128 characters; titles at most 120; content at most 10,000 (`10_000` is ten thousand, the underscore is only for reading).

```python
def validate_username(raw: str) -> str:
    """Return the canonical (lower-case) username or raise ``InvalidInputError``."""
    username = raw.strip().lower()
    if USERNAME_PATTERN.fullmatch(username) is None:
        raise InvalidInputError("username", "use 3 to 32 letters, digits or underscores")
    return username
```

`validate_username` removes spaces at the ends and lower-cases the text, so `Alice` and `alice` are the same account. `fullmatch` requires the whole text to match the pattern; anything else raises `InvalidInputError` for the field `username`. The cleaned text is returned.

```python
def validate_password(raw: str) -> str:
    """Length is the only rule that matters (NIST SP 800-63B); the upper bound stops hash-time abuse."""
    if not PASSWORD_MIN_LENGTH <= len(raw) <= PASSWORD_MAX_LENGTH:
        raise InvalidInputError("password", f"use {PASSWORD_MIN_LENGTH} to {PASSWORD_MAX_LENGTH} characters")
    return raw
```

`validate_password` checks only the length. The docstring cites NIST SP 800-63B, a US standard that says length is what matters and composition rules (needing a digit and a symbol) do not help. The upper bound stops someone from sending a megabyte "password" to make the server spend time hashing it.

```python
def validate_note_title(raw: str) -> str:
    """A note title is one non-empty line of at most 120 characters."""
    title = raw.strip()
    if not title or len(title) > TITLE_MAX_LENGTH:
        raise InvalidInputError("title", f"use 1 to {TITLE_MAX_LENGTH} characters")
    if "\x00" in title or "\n" in title or "\r" in title:
        raise InvalidInputError("title", "use a single line")
    return title
```

`validate_note_title` removes the ends' spaces, then refuses an empty title or one over 120 characters, and refuses a NUL character, a newline or a carriage return so a title is one line.

```python
def validate_note_content(raw: str) -> str:
    """Note content is free text up to 10,000 characters. Markup is allowed because output encoding handles it;
    a NUL byte is refused because PostgreSQL cannot store it."""
    if len(raw) > CONTENT_MAX_LENGTH:
        raise InvalidInputError("content", f"use at most {CONTENT_MAX_LENGTH} characters")
    if "\x00" in raw:
        raise InvalidInputError("content", "remove the NUL character")
    return raw
```

`validate_note_content` allows up to 10,000 characters of free text, including markup, because the page encodes it on output. A NUL character is refused because PostgreSQL cannot store it.

### Line by line: `src/notes_app/application/policy.py`

```python
"""The production access policy: the domain rule, nothing more."""
```

The docstring: the production access policy is the domain rule, nothing more.

```python
from __future__ import annotations

from collections.abc import Collection

from notes_app.domain.access import Access, access_to_note
```

Imports: `Collection` and the domain's `Access` and `access_to_note`.

```python
class OwnerOrSharedPolicy:
    """Owner writes, a user the note is shared with reads, everyone else gets nothing."""

    def access(self, *, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
        """The level of access the user has to the note."""
        return access_to_note(owner_id=owner_id, shared_with=shared_with, user_id=user_id)
```

`OwnerOrSharedPolicy` is the production implementation of the `AccessPolicy` port: its one method `access` just calls the pure domain function. It exists so the policy can be replaced: a test swaps in the deliberately open policy from `weaknesses/open_policy.py` to prove the authorization tests fail without the real rule.

### Line by line: `src/notes_app/application/ports.py`

A **port** is an interface: a list of method names and types that a use case needs, with no code. The real work is done by an adapter in `infrastructure`; tests use fakes.

```python
"""Ports: what the use cases need from the outside world. Adapters live in ``infrastructure``."""
```

The docstring: ports are what the use cases need from the outside world.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
from collections.abc import Collection
from datetime import datetime
from typing import Protocol
```

`Collection`, `datetime` and `Protocol`. A `Protocol` describes an interface by shape: any class with these methods counts as an implementation, without inheriting from anything.

```python
from notes_app.domain.access import Access
from notes_app.domain.models import AuditEvent, Note, Session, User, VisibleNote
```

Imports of the domain pieces used in the signatures.

```python
class UserRepository(Protocol):
    """Storage of users."""

    def add(self, username: str, password_hash: str) -> User:
        """Insert a user; raise ``UsernameTakenError`` when the username exists."""

    def by_username(self, username: str) -> User | None:
        """Find a user by canonical username."""

    def by_id(self, user_id: int) -> User | None:
        """Find a user by id."""

    def update_password_hash(self, user_id: int, password_hash: str) -> None:
        """Replace the stored hash (after a parameter upgrade)."""
```

`UserRepository`: `add` (raises `UsernameTakenError` if the name exists), `by_username`, `by_id`, and `update_password_hash` (used after a parameter upgrade). The methods have only a docstring as body, which is legal Python and enough for a Protocol.

```python
class NoteRepository(Protocol):
    """Storage of notes and their shares. Every method takes values; none builds SQL from them."""

    def add(self, owner_id: int, title: str, content: str) -> Note:
        """Insert a note."""

    def get(self, note_id: int) -> Note | None:
        """Fetch one note by id, whoever owns it. Authorization is the service's job."""

    def shared_with(self, note_id: int) -> frozenset[int]:
        """The ids of the users a note is shared with."""

    def update(self, note_id: int, title: str, content: str) -> Note:
        """Replace a note's title and content."""

    def delete(self, note_id: int) -> None:
        """Delete a note and its shares."""

    def share(self, note_id: int, user_id: int) -> None:
        """Share a note with a user (idempotent)."""

    def list_visible(self, user_id: int) -> list[VisibleNote]:
        """Every note the user owns or has been given, newest first."""
```

`NoteRepository`: `add`, `get` (any note, whoever owns it; authorization is the service's job), `shared_with` (a frozen set of user ids), `update`, `delete`, `share` (idempotent: sharing twice is the same as once) and `list_visible` (every note the user owns or was given, newest first). The docstring rule: every method takes values and none builds SQL from them.

```python
class SessionRepository(Protocol):
    """Storage of sessions, keyed by the hash of the cookie value."""

    def add(self, session: Session) -> None:
        """Insert a session."""

    def get(self, token_hash: str) -> Session | None:
        """Fetch a session by token hash."""

    def touch(self, token_hash: str, seen_at: datetime) -> None:
        """Record activity."""

    def delete(self, token_hash: str) -> None:
        """Remove a session (sign-out or rotation)."""

    def purge_expired(self, now: datetime) -> int:
        """Remove every session past its absolute expiry; return how many."""
```

`SessionRepository`: sessions are keyed by the hash of the cookie value. `add`, `get`, `touch` (record activity), `delete` (sign-out or rotation) and `purge_expired`, which removes sessions past their absolute expiry and returns how many.

```python
class AuditLog(Protocol):
    """Append-only record of security events."""

    def record(self, event: AuditEvent) -> None:
        """Write one event."""
```

`AuditLog`: append-only, with one method `record`.

```python
class PasswordHasher(Protocol):
    """Slow, salted password hashing."""

    def hash(self, password: str) -> str:
        """Hash with a fresh random salt."""

    def verify(self, password: str, encoded: str) -> bool:
        """Constant-effort check of a password against a stored hash."""

    def needs_rehash(self, encoded: str) -> bool:
        """True when the stored hash uses weaker parameters than the current ones."""

    def spend_equal_effort(self, password: str) -> None:
        """Do the work of a verification for a user that does not exist, so timing does not reveal them."""
```

`PasswordHasher`: `hash` (with a fresh random salt), `verify` (constant-effort check), `needs_rehash` (the stored hash uses weaker parameters than the current ones) and `spend_equal_effort`, which does the work of a verification for a user that does not exist so that the time taken does not reveal which usernames exist.

```python
class LoginThrottle(Protocol):
    """Limits failed sign-ins per client and username."""

    def check(self, key: str, now: datetime) -> None:
        """Raise ``LoginThrottledError`` when the key is over the limit."""

    def record_failure(self, key: str, now: datetime) -> None:
        """Count one failed sign-in."""

    def reset(self, key: str) -> None:
        """Forget the failures (after a successful sign-in)."""
```

`LoginThrottle`: `check` raises when the key is over the limit, `record_failure` counts one failure and `reset` forgets failures after a good sign-in.

```python
class AccessPolicy(Protocol):
    """Decides what a user may do with a note."""

    def access(self, *, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
        """The level of access the user has."""
```

`AccessPolicy`: one method returning the `Access` level.

```python
class Clock(Protocol):
    """Time, injected so tests are deterministic."""

    def now(self) -> datetime:
        """The current time, timezone-aware (UTC)."""
```

`Clock`: `now()` returns the current time with a time zone (UTC). It is injected so tests can control time.

```python
class TokenGenerator(Protocol):
    """Unguessable tokens for sessions and CSRF."""

    def new_token(self) -> str:
        """A URL-safe token with at least 256 bits of randomness."""
```

`TokenGenerator`: `new_token()` returns a URL-safe token with at least 256 bits of randomness, for sessions and CSRF.

### Line by line: `src/notes_app/application/accounts.py`

```python
"""Sign-up and sign-in."""
```

The docstring: sign-up and sign-in.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
from notes_app.application.ports import AuditLog, Clock, LoginThrottle, PasswordHasher, UserRepository
from notes_app.domain.errors import AuthenticationFailedError, InvalidInputError, LoginThrottledError
from notes_app.domain.models import AuditAction, AuditEvent, User
from notes_app.domain.validation import validate_password, validate_username
```

Imports from the application layer (the ports) and the domain: the errors, the models and the validators for username and password. The service never imports a database or argon2 directly; it receives them as ports.

```python
class AccountService:
    """Registers users and checks credentials. Passwords are hashed here and appear nowhere else."""
```

`AccountService` registers users and checks credentials. The docstring states the rule: passwords are hashed here and appear nowhere else.

```python
    def __init__(
        self,
        users: UserRepository,
        hasher: PasswordHasher,
        throttle: LoginThrottle,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._throttle = throttle
        self._audit = audit
        self._clock = clock
```

The constructor receives five collaborators: the user store, the password hasher, the login throttle, the audit log and the clock, and keeps them as private attributes (the underscore marks them private). Handing them in from outside is **dependency injection**; it lets the tests pass fakes.

```python
    def register(self, username: str, password: str, ip: str) -> User:
        """Create a user with a salted hash. Raises ``InvalidInputError`` or ``UsernameTakenError``."""
        canonical = validate_username(username)
        user = self._users.add(canonical, self._hasher.hash(validate_password(password)))
        self._audit.record(AuditEvent(AuditAction.SIGNUP, "success", user.id, ip))
        return user
```

`register` validates the username (canonical lower-case form) and the password (length), hashes the password with a fresh salt, stores the user and writes a `signup` audit row. The raw password is never stored and not passed on after hashing. A duplicate name makes the repository raise `UsernameTakenError`.

```python
    def authenticate(self, username: str, password: str, ip: str) -> User:
        """Return the user for a correct username and password.

        Raises ``LoginThrottledError`` when the client has failed too often, and ``AuthenticationFailedError``
        for any wrong credential. The two failure causes (unknown user, wrong password) are indistinguishable in
        the response and in the time taken.
        """
```

`authenticate` returns the user for correct credentials. The docstring promises two things: throttled clients are refused, and the two failure causes (no such user, wrong password) look the same in the response and in the time taken.

```python
        key = f"{ip}|{username.strip().lower()}"
        now = self._clock.now()
```

The throttle key joins the client's IP and the cleaned username with a `|`, so a failure limit applies per client and per account. `now` comes from the injected clock.

```python
        try:
            self._throttle.check(key, now)
        except LoginThrottledError:
            self._audit.record(AuditEvent(AuditAction.LOGIN_THROTTLED, "refused", None, ip))
            raise
```

The throttle is asked first. If the client is over the limit, a `login.throttled` audit row is written (with no user id) and the same error is raised again with a bare `raise`, so the web layer answers 429. No password check happens for a throttled client, which also stops an attacker from using the hash cost as a free guessing machine.

```python
        user = self._find(username)
```

`_find` looks the user up by name.

```python
        if user is None or not self._hasher.verify(password, user.password_hash):
            if user is None:
                self._hasher.spend_equal_effort(password)
            self._throttle.record_failure(key, now)
            self._audit.record(AuditEvent(AuditAction.LOGIN_FAILURE, "failure", user.id if user else None, ip))
            raise AuthenticationFailedError("invalid username or password")
```

If the user does not exist or the password does not verify, this is a failure. If there is no such user, `spend_equal_effort` does the same slow hashing work that a real check would have done, so an attacker cannot tell a missing account from a wrong password by timing. The failure is counted against the key, an audit row `login.failure` is written (with the user's id when there is one) and `AuthenticationFailedError` is raised with a message that does not say which part was wrong.

```python
        self._throttle.reset(key)
```

Success: the failure count for the key is forgotten.

```python
        if self._hasher.needs_rehash(user.password_hash):
            self._users.update_password_hash(user.id, self._hasher.hash(password))
```

If the stored hash uses weaker parameters than today's, the hash is recomputed with the current ones and stored. This is the only moment the plain password is available, so the upgrade happens at sign-in.

```python
        self._audit.record(AuditEvent(AuditAction.LOGIN_SUCCESS, "success", user.id, ip))
        return user
```

A `login.success` audit row is written and the user returned.

```python
    def get_user(self, user_id: int) -> User | None:
        """The user with this id, for the page header of a signed-in session."""
        return self._users.by_id(user_id)
```

`get_user` finds a user by id, for the page header of a signed-in session.

```python
    def _find(self, username: str) -> User | None:
        try:
            return self._users.by_username(validate_username(username))
        except InvalidInputError:
            return None
```

`_find` validates the username before the lookup. If validation fails (a name that could never exist, such as one with spaces) the answer is `None`, which flows into the same failure path as an unknown user.

### Line by line: `src/notes_app/application/notes.py`

```python
"""Notes use cases. Every read, update, delete and share goes through one authorization check."""
```

The docstring: every read, update, delete and share goes through one authorization check. The lesson's main rule is that a missing check in one route is the classic hole, so there is only one place that decides.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
from notes_app.application.ports import AccessPolicy, AuditLog, NoteRepository, UserRepository
from notes_app.domain.access import Access
from notes_app.domain.errors import InvalidInputError, NoteForbiddenError, NoteNotFoundError
from notes_app.domain.models import AuditAction, AuditEvent, Note, VisibleNote
from notes_app.domain.validation import validate_note_content, validate_note_title, validate_username
```

Imports: the ports, the `Access` levels, three errors, the models and three validators.

```python
class NoteService:
    """The service layer of the threat model: the boundary where "does this user own or share this note?" is
    asked on every request, with the answer looked up fresh from the database."""
```

`NoteService` is the service layer of the threat model: the boundary where "does this user own or share this note?" is asked on every request, with the answer looked up fresh from the database rather than remembered from earlier.

```python
    def __init__(self, notes: NoteRepository, users: UserRepository, policy: AccessPolicy, audit: AuditLog) -> None:
        self._notes = notes
        self._users = users
        self._policy = policy
        self._audit = audit
```

The constructor receives the note store, the user store, the access policy and the audit log.

```python
    def create(self, user_id: int, title: str, content: str) -> Note:
        """Create a note owned by the user."""
        return self._notes.add(user_id, validate_note_title(title), validate_note_content(content))
```

`create` validates title and content and stores a note owned by the user. Creation needs no authorization check because every signed-in user may create notes for themselves.

```python
    def get(self, user_id: int, note_id: int, ip: str) -> Note:
        """Read a note the user owns or has been given."""
        return self._authorize(user_id, note_id, Access.READ, ip)
```

`get` requires at least `READ` access. It returns the note if allowed; otherwise `_authorize` raises.

```python
    def update(self, user_id: int, note_id: int, title: str | None, content: str | None, ip: str) -> Note:
        """Change a note's title or content; only the owner may."""
        note = self._authorize(user_id, note_id, Access.WRITE, ip)
        new_title = validate_note_title(title) if title is not None else note.title
        new_content = validate_note_content(content) if content is not None else note.content
        return self._notes.update(note_id, new_title, new_content)
```

`update` requires `WRITE`. `title` and `content` are optional: `None` means "keep the old value". Each new value is validated before the update is stored. Because the authorization check runs first, a reader never reaches the validators.

```python
    def delete(self, user_id: int, note_id: int, ip: str) -> None:
        """Delete a note; only the owner may."""
        self._authorize(user_id, note_id, Access.WRITE, ip)
        self._notes.delete(note_id)
        self._audit.record(AuditEvent(AuditAction.NOTE_DELETED, "success", user_id, ip, (("note_id", str(note_id)),)))
```

`delete` requires `WRITE`, deletes the note (the repository also removes its shares) and writes a `note.deleted` audit row with the note id as detail.

```python
    def share(self, user_id: int, note_id: int, username: str, ip: str) -> None:
        """Share a note with one other user by username; only the owner may."""
        self._authorize(user_id, note_id, Access.WRITE, ip)
        target = self._users.by_username(validate_username(username))
        if target is None or target.id == user_id:
            raise InvalidInputError("username", "choose another existing user")
        self._notes.share(note_id, target.id)
        detail = (("note_id", str(note_id)), ("shared_with", str(target.id)))
        self._audit.record(AuditEvent(AuditAction.NOTE_SHARED, "success", user_id, ip, detail))
```

`share` requires `WRITE` (only the owner may share). The target is found by validated username; a missing user, or the owner themself, raises `InvalidInputError`. The share is stored (idempotent) and a `note.shared` audit row records the note id and the target's id.

```python
    def list_visible(self, user_id: int) -> list[VisibleNote]:
        """The notes the user owns or has been given."""
        return self._notes.list_visible(user_id)
```

`list_visible` asks the repository for the notes the user owns or has been given.

```python
    def _authorize(self, user_id: int, note_id: int, needed: Access, ip: str) -> Note:
        note = self._notes.get(note_id)
        if note is None:
            raise NoteNotFoundError(f"note {note_id}")
```

`_authorize` is the one check. It fetches the note; a missing note raises `NoteNotFoundError`.

```python
        access = self._policy.access(
            owner_id=note.owner_id, shared_with=self._notes.shared_with(note_id), user_id=user_id
        )
```

It asks the policy for the user's access, passing the owner id, the set of shared user ids (read fresh from the database) and the user id.

```python
        if access >= needed:
            return note
```

If the access level is at least what the action needs (`Access` is ordered), the note is returned.

```python
        reason = "no_access" if access is Access.NONE else "read_only"
        self._audit.record(
            AuditEvent(
                AuditAction.NOTE_ACCESS_DENIED, "refused", user_id, ip, (("note_id", str(note_id)), ("reason", reason))
            )
        )
```

Otherwise the denial is recorded: reason `no_access` when the level is `NONE`, `read_only` when the user is a reader trying to write. An audit row `note.access_denied` is written with the note id and the reason.

```python
        if access is Access.NONE:
            raise NoteNotFoundError(f"note {note_id}")
        raise NoteForbiddenError(f"note {note_id}")
```

A user with no access gets `NoteNotFoundError` (the same error as a missing note, so a response does not confirm that the id exists). A reader who tried to write gets `NoteForbiddenError`, because that person can already see the note and hiding it would be pointless.

### Line by line: `src/notes_app/application/sessions.py`

```python
"""Server-side sessions with an opaque cookie value, rotation at sign-in and idle and absolute expiry."""
```

The docstring: server-side sessions with an opaque cookie value, rotation at sign-in, and idle and absolute expiry. A **session** is how the server remembers a signed-in user between requests: the browser holds a random cookie value, the server holds the record. **Opaque** means the cookie value carries no meaning itself; it is only a key.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import hashlib
import hmac
from dataclasses import dataclass
from datetime import timedelta
```

Imports: `hashlib` (hash functions), `hmac` (for a safe comparison), `dataclass` and `timedelta`.

```python
from notes_app.application.ports import Clock, SessionRepository, TokenGenerator
from notes_app.domain.models import Session
```

The ports and the `Session` model.

```python
TOUCH_INTERVAL = timedelta(seconds=60)
```

`TOUCH_INTERVAL` is 60 seconds: the stored last-activity time is updated at most once a minute, so the database is not written on every request.

```python
@dataclass(frozen=True, slots=True)
class SessionPolicy:
    """Lifetimes in seconds: how long an idle session lives, how long any session lives, and how long the
    anonymous session that carries the sign-in form's CSRF token lives."""

    idle_seconds: int
    absolute_seconds: int
    anonymous_seconds: int
```

`SessionPolicy` holds three lifetimes in seconds: how long an idle signed-in session lives, how long any session lives at most, and how long the anonymous session that carries the sign-in form's CSRF token lives.

```python
@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session and the raw cookie value, the only moment the raw value exists on the server."""

    raw_token: str
    session: Session
    max_age_seconds: int
```

`IssuedSession` bundles a new session, the raw cookie value and the lifetime. The raw value exists on the server only at this moment; afterwards only its hash is stored.

```python
def hash_token(raw_token: str) -> str:
    """The stored form of a cookie value: a database read never yields a usable session."""
    return hashlib.sha256(raw_token.encode()).hexdigest()
```

`hash_token` is the stored form of a cookie value: the SHA-256 hash in hexadecimal. A hash cannot be turned back into the value, so even someone who reads the sessions table cannot use the hashes as cookies. The random tokens are long enough (256 bits) that a plain fast hash is safe here, unlike passwords.

```python
class SessionService:
    """Creates, resolves, rotates and ends sessions."""
```

`SessionService` creates, resolves, rotates and ends sessions.

```python
    def __init__(
        self, sessions: SessionRepository, tokens: TokenGenerator, clock: Clock, policy: SessionPolicy
    ) -> None:
        self._sessions = sessions
        self._tokens = tokens
        self._clock = clock
        self._policy = policy
```

The constructor receives the session store, the token generator, the clock and the policy.

```python
    def start_anonymous(self) -> IssuedSession:
        """A session before sign-in, so the sign-in and sign-up forms carry a CSRF token."""
        return self._issue(user_id=None, lifetime_seconds=self._policy.anonymous_seconds)
```

`start_anonymous` issues a session with no user, so the sign-in and sign-up forms have a CSRF token to put in a hidden field.

```python
    def sign_in(self, previous_raw_token: str | None, user_id: int) -> IssuedSession:
        """Replace any earlier session with a new one for the user (defeats session fixation)."""
        if previous_raw_token:
            self._sessions.delete(hash_token(previous_raw_token))
        self._sessions.purge_expired(self._clock.now())
        return self._issue(user_id=user_id, lifetime_seconds=self._policy.absolute_seconds)
```

`sign_in` deletes the earlier session (the cookie the browser had before signing in) if there was one, deletes expired sessions from the store, and issues a brand new session for the user with a new token. Issuing a new token at sign-in **defeats session fixation**: an attacker who planted a known session value in the victim's browser before sign-in finds it dead afterwards.

```python
    def resolve(self, raw_token: str | None) -> Session | None:
        """The live session for a cookie value, or ``None`` when unknown, idle too long or past its expiry."""
        if not raw_token:
            return None
```

`resolve` takes the raw cookie value and returns the live session or `None`. No value means no session.

```python
        token_hash = hash_token(raw_token)
        session = self._sessions.get(token_hash)
        if session is None:
            return None
```

The value is hashed and the session fetched; an unknown hash gives `None`.

```python
        now = self._clock.now()
        idle_limit = session.last_seen_at + timedelta(seconds=self._policy.idle_seconds)
        if now >= session.expires_at or (session.user_id is not None and now >= idle_limit):
            self._sessions.delete(token_hash)
            return None
```

The idle limit is the last activity plus the idle time. A session is dead if the current time has passed its absolute expiry, or if it belongs to a signed-in user and has been idle too long. Anonymous sessions have no idle rule, only the short absolute one. A dead session is deleted from the store.

```python
        if now - session.last_seen_at >= TOUCH_INTERVAL:
            self._sessions.touch(token_hash, now)
        return session
```

A live session whose last activity is a minute or more old gets its activity time refreshed. The session is returned.

```python
    def sign_out(self, raw_token: str | None) -> None:
        """Delete the session on the server; the cookie value stops meaning anything."""
        if raw_token:
            self._sessions.delete(hash_token(raw_token))
```

`sign_out` deletes the session on the server. The browser may keep the cookie, but it no longer means anything.

```python
    @staticmethod
    def csrf_valid(session: Session, supplied: str | None) -> bool:
        """Constant-time comparison of the supplied token with the session's."""
        return supplied is not None and hmac.compare_digest(session.csrf_token.encode(), supplied.encode())
```

`csrf_valid` is a static method (it needs no object) that compares the supplied token with the session's using `hmac.compare_digest`, which takes the same time no matter where the first difference is, so response timing leaks nothing about the token. A missing token is invalid.

```python
    def _issue(self, *, user_id: int | None, lifetime_seconds: int) -> IssuedSession:
        now = self._clock.now()
        raw_token = self._tokens.new_token()
        session = Session(
            token_hash=hash_token(raw_token),
            user_id=user_id,
            csrf_token=self._tokens.new_token(),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=lifetime_seconds),
        )
        self._sessions.add(session)
        return IssuedSession(raw_token, session, lifetime_seconds)
```

`_issue` creates the session: the current time, a fresh raw token for the cookie and another fresh token for CSRF, a record that stores only the hash of the cookie value, the creation and last-seen times set to now and the expiry set to now plus the lifetime. It stores the record and returns it with the raw token and lifetime.

### Line by line: `src/notes_app/infrastructure/clock.py`

```python
"""System clock and token source."""

from __future__ import annotations
```

The docstring and the type-hint line.

```python
import secrets
from datetime import UTC, datetime
```

`secrets` is the standard module for security-grade randomness; `datetime` with `UTC` gives time-zone-aware times.

```python
class SystemClock:
    """The real time, in UTC."""

    def now(self) -> datetime:
        """The current UTC time."""
        return datetime.now(UTC)
```

`SystemClock` implements the `Clock` port: `now()` returns the current UTC time.

```python
class SecretsTokenGenerator:
    """Tokens from the operating system's CSPRNG: 32 bytes, 256 bits."""

    def new_token(self) -> str:
        """A URL-safe token."""
        return secrets.token_urlsafe(32)
```

`SecretsTokenGenerator` implements `TokenGenerator`: `secrets.token_urlsafe(32)` returns 32 random bytes (256 bits) from the operating system's cryptographic random source, written in URL-safe text.

### Line by line: `src/notes_app/infrastructure/logging.py`

```python
"""Structured (JSON) logging with redaction, so a secret that reaches a log call never reaches the log."""
```

The docstring: structured JSON logging with redaction, so a secret that reaches a log call never reaches the log.

```python
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any
```

Imports: `json`, `logging`, `re`, `sys`, `datetime` with `UTC`, and `Any`.

```python
REDACTED = "[redacted]"
_SENSITIVE_KEY = re.compile(r"pass(word|wd)?|secret|token|cookie|authorization|csrf|session|api[_-]?key", re.IGNORECASE)
```

`REDACTED` is the replacement text. `_SENSITIVE_KEY` is a case-insensitive regular expression matching names that suggest a secret: `pass`, `password`, `passwd`, `secret`, `token`, `cookie`, `authorization`, `csrf`, `session`, `api_key` (also `api-key`, `apikey`).

```python
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}
```

`_RESERVED` is the set of attribute names every standard `LogRecord` already has plus `message` and `asctime`; anything else on a record was added by the caller through `extra=`.

```python
def redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Replace the value of every field whose name looks sensitive."""
    return {key: REDACTED if _SENSITIVE_KEY.search(key) else value for key, value in fields.items()}
```

`redact` returns a new dictionary where each value whose key matches the pattern is replaced.

```python
class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, and the call's extra fields, redacted."""

    def format(self, record: logging.LogRecord) -> str:
        """Render a record as a single JSON line."""
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(redact({key: value for key, value in record.__dict__.items() if key not in _RESERVED}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))
```

`JsonFormatter.format` builds a dictionary with the record's time (ISO 8601, milliseconds), level, logger name and message, adds the caller's extra fields after redaction, adds the stack trace under `exception` if there is one, and returns compact JSON (`default=str` turns anything unserializable into text).

```python
def configure_logging(level: str) -> None:
    """Send every log record to standard error as JSON at the given level."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
```

`configure_logging` makes a handler that writes to standard error with that formatter, makes it the only handler of the root logger and sets the level.

### Line by line: `src/notes_app/infrastructure/weaknesses/concatenated_notes.py`

```python
"""WEAKNESS (UNSAFE_SQL_CONCATENATION): a note insert that splices its values into the statement text."""
```

The docstring: a deliberate weakness, a note insert that splices its values into the statement text.

```python
from __future__ import annotations

from notes_app.domain.models import Note
from notes_app.infrastructure.postgres.notes import PostgresNoteRepository, to_note
```

Imports of `Note` and of the real PostgreSQL repository, which this class extends.

```python
class ConcatenatedNoteRepository(PostgresNoteRepository):
    """What the parameterized-query control replaces. A quote character in a title or in the content now changes
    the statement's structure, so a note containing one is a syntax error instead of text."""
```

`ConcatenatedNoteRepository` inherits everything and replaces only `add`. A quote character in a title or content now changes the structure of the statement, so such a note becomes a syntax error instead of text.

```python
    def add(self, owner_id: int, title: str, content: str) -> Note:
        """Insert by building the statement as a string."""
        statement = (
            "INSERT INTO notes (owner_id, title, content) VALUES ("  # noqa: S608 - deliberate weakness, APP_ENV=test only
            + str(owner_id)
            + ", '"
            + title
            + "', '"
            + content
            + "') RETURNING id, owner_id, title, content, created_at, updated_at"
        )
```

`add` builds the statement with `+`, pasting the owner id, the title and the content into the SQL text. The `noqa: S608` comment tells ruff the string-built SQL is intentional.

```python
        with self._database.connection() as connection:
            row = connection.execute(statement).fetchone()
        assert row is not None  # noqa: S101
        return to_note(row)
```

It runs the statement and builds a `Note` from the returned row.

### Line by line: `src/notes_app/infrastructure/weaknesses/open_policy.py`

```python
"""WEAKNESS (UNSAFE_SKIP_OWNERSHIP_CHECK): an access policy that trusts any id."""
```

The docstring: a deliberate weakness, an access policy that trusts any id.

```python
from __future__ import annotations

from collections.abc import Collection

from notes_app.domain.access import Access
```

Imports of `Collection` and `Access`.

```python
class AllowEverythingPolicy:
    """What the per-request authorization check replaces: if you know the id, you may do anything with it."""

    def access(self, *, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
        """Full access for everyone."""
        return Access.WRITE
```

`AllowEverythingPolicy.access` ignores its arguments and returns `WRITE` for everyone. With it, anyone who knows a note id may do anything, which is exactly what the authorization tests must catch.

### Line by line: `src/notes_app/infrastructure/weaknesses/unsalted_sha256_hasher.py`

```python
"""WEAKNESS (UNSAFE_WEAK_PASSWORD_HASH): an unsalted fast digest instead of a password hash."""
```

The docstring: a deliberate weakness, an unsalted fast digest instead of a password hash.

```python
from __future__ import annotations

import hashlib
import hmac
```

Imports of `hashlib` and `hmac`.

```python
class UnsaltedSha256Hasher:
    """What the argon2 control replaces: fast, no salt, identical passwords give identical hashes."""

    def hash(self, password: str) -> str:
        """A bare SHA-256 digest."""
        return hashlib.sha256(password.encode()).hexdigest()
```

`hash` returns a bare SHA-256 hexadecimal digest: fast, no salt, so equal passwords give equal hashes and a leaked table can be attacked quickly.

```python
    def verify(self, password: str, encoded: str) -> bool:
        """Compare digests."""
        return hmac.compare_digest(self.hash(password), encoded)
```

`verify` compares digests with `hmac.compare_digest`.

```python
    def needs_rehash(self, encoded: str) -> bool:
        """Never; there are no parameters."""
        return False
```

`needs_rehash` is always false because there are no parameters.

```python
    def spend_equal_effort(self, password: str) -> None:
        """Nothing to equalize."""
```

`spend_equal_effort` does nothing; there is no cost to equalize.

### Line by line: `src/notes_app/interfaces/composition.py`

```python
"""The composition root: the one place that knows which adapter implements which port."""
```

The docstring: the **composition root**, the one place that knows which adapter implements which port.

```python
from __future__ import annotations

from dataclasses import dataclass
```

Type hints kept as text and `dataclass`.

```python
from notes_app.application.accounts import AccountService
from notes_app.application.notes import NoteService
from notes_app.application.policy import OwnerOrSharedPolicy
from notes_app.application.ports import AccessPolicy, AuditLog, PasswordHasher
from notes_app.application.sessions import SessionService
from notes_app.infrastructure.argon2_hasher import Argon2PasswordHasher
from notes_app.infrastructure.clock import SecretsTokenGenerator, SystemClock
from notes_app.infrastructure.postgres.audit import PostgresAuditLog
from notes_app.infrastructure.postgres.database import Database
from notes_app.infrastructure.postgres.notes import PostgresNoteRepository
from notes_app.infrastructure.postgres.sessions import PostgresSessionRepository
from notes_app.infrastructure.postgres.throttle import PostgresLoginThrottle
from notes_app.infrastructure.postgres.users import PostgresUserRepository
from notes_app.infrastructure.settings import Settings
from notes_app.infrastructure.weaknesses.concatenated_notes import ConcatenatedNoteRepository
from notes_app.infrastructure.weaknesses.open_policy import AllowEverythingPolicy
from notes_app.infrastructure.weaknesses.unsalted_sha256_hasher import UnsaltedSha256Hasher
```

Imports of the services, the ports, every adapter and the three deliberate weaknesses. This is the one module allowed to import both sides.

```python
@dataclass(frozen=True, slots=True)
class Container:
    """The wired application: settings, the database and the three services the HTTP layer calls."""

    settings: Settings
    database: Database
    audit: AuditLog
    accounts: AccountService
    sessions: SessionService
    notes: NoteService
```

`Container` is a frozen record of the wired application: settings, the database, the audit log and the three services the HTTP layer calls.

```python
def build_container(settings: Settings) -> Container:
    """Wire adapters into use cases. A deliberate weakness (APP_ENV=test only) swaps one adapter here."""
    weak = settings.weaknesses
    database = Database(settings.database)
    clock = SystemClock()
    audit = PostgresAuditLog(database)
    users = PostgresUserRepository(database)
```

`build_container` takes the settings, remembers the weakness switches, builds the database pool, the clock, the audit log and the user repository.

```python
    hasher: PasswordHasher = (
        UnsaltedSha256Hasher()
        if weak.weak_password_hash
        else Argon2PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_kib=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
        )
    )
```

The hasher is the unsalted SHA-256 only when the weakness is on; otherwise argon2 with the configured cost, memory and parallelism.

```python
    policy: AccessPolicy = AllowEverythingPolicy() if weak.skip_ownership_check else OwnerOrSharedPolicy()
    notes_repository = (
        ConcatenatedNoteRepository(database) if weak.sql_concatenation else PostgresNoteRepository(database)
    )
```

The access policy is the open one only when the ownership-check weakness is on; the note repository is the string-concatenating one only when the SQL weakness is on.

```python
    throttle = PostgresLoginThrottle(
        database, max_failures=settings.login_max_failures, window_seconds=settings.login_window_seconds
    )
```

The throttle is built with the configured limit and window.

```python
    return Container(
        settings=settings,
        database=database,
        audit=audit,
        accounts=AccountService(users, hasher, throttle, audit, clock),
        sessions=SessionService(PostgresSessionRepository(database), SecretsTokenGenerator(), clock, settings.session),
        notes=NoteService(notes_repository, users, policy, audit),
    )
```

The container is returned with the account service (users, hasher, throttle, audit, clock), the session service (session repository, token generator, clock, session policy) and the note service (notes, users, policy, audit).

### Line by line: `src/notes_app/interfaces/health_cli.py`

```python
"""``notes-app-health``: exit 0 when the running server answers ``/readyz`` (the container's health check)."""
```

The docstring: the command `notes-app-health` exits 0 when the running server answers `/readyz`; the container's health check runs it.

```python
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
```

Imports: `os`, `sys`, and the standard URL tools `urllib.error` and `urllib.request`.

```python
def main() -> int:
    """Probe the readiness endpoint on the loopback address; print the outcome and return the exit code."""
    port = os.environ.get("APP_PORT", "8047")
    url = f"http://127.0.0.1:{port}/readyz"
```

`main` reads the port from `APP_PORT` (default 8047) and builds the address on `127.0.0.1`, the loopback address that always means "this same machine".

```python
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            ok = response.status == 200
```

It opens the address with a three-second limit and records whether the status was 200.

```python
    except (urllib.error.URLError, OSError) as error:
        print(f"unhealthy: {error}", file=sys.stderr)
        return 1
```

A network error prints `unhealthy: <reason>` to standard error and returns 1.

```python
    print("healthy" if ok else "unhealthy")
    return 0 if ok else 1
```

Otherwise it prints `healthy` or `unhealthy` and returns 0 or 1. Docker treats exit code 0 as healthy.

```python
if __name__ == "__main__":
    sys.exit(main())
```

When run as a program, the return value becomes the exit code.

### Line by line: `src/notes_app/interfaces/demo_cli.py`

```python
"""``notes-app-demo``: the lesson's scenario against a running server, printed as checked steps.

It signs up generated users (passwords are random and never printed), then shows each control from the threat
model working: cookie flags, headers, output encoding, authorization, CSRF, throttling, sign-out.
"""
```

The docstring: the command `notes-app-demo` runs the lesson's scenario against a running server and prints each check. It signs up generated users (random passwords, never printed) and shows each control from the threat model working: cookie flags, headers, output encoding, authorization, CSRF, throttling and sign-out.

```python
from __future__ import annotations
```

Type hints kept as text.

```python
import argparse
import http.client
import json
import os
import re
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode
```

Imports: `argparse` (command-line options), `http.client` (a small HTTP client), `json`, `os`, `re` (regular expressions), `secrets` (random values), `sys`, `Callable`, `dataclass` and `urlencode` (turns a dictionary into form text).

```python
from notes_app.interfaces.http.security import CSRF_HEADER, SESSION_COOKIE
```

The names of the session cookie and the CSRF header are taken from the application so the demo cannot drift from it.

```python
HOSTILE = "<script>alert(1)</script> and a quote: ' OR '1'='1"
_CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')
REQUIRED_HEADERS = ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options")
```

`HOSTILE` is the attack text the demo stores in a note: a script tag and a SQL-injection-style quote. `_CSRF_FIELD` is a regular expression that finds `name="csrf_token" value="..."` in a page and captures the value. `REQUIRED_HEADERS` are three headers every response must have.

```python
@dataclass(frozen=True, slots=True)
class Step:
    """One checked claim of the scenario."""

    name: str
    passed: bool
    detail: str
```

`Step` is one checked claim: a name, whether it passed and a detail text.

```python
@dataclass(frozen=True, slots=True)
class Reply:
    """The parts of an HTTP response the scenario looks at."""

    status: int
    headers: dict[str, str]
    set_cookies: tuple[str, ...]
    body: str

    def json(self) -> dict[str, object]:
        """The body as a JSON object."""
        parsed = json.loads(self.body)
        return parsed if isinstance(parsed, dict) else {}
```

`Reply` keeps the parts of an HTTP response the scenario looks at: status, headers, the list of `Set-Cookie` headers and the body text. Its `json` method parses the body as a JSON object, or returns an empty dictionary.

```python
class Browser:
    """A tiny HTTP client with one cookie. It sets the Secure cookie by hand because plain-http clients rightly
    refuse to send it; a real browser treats http://localhost as secure."""

    def __init__(self, host: str, port: int) -> None:
        self._host, self._port = host, port
        self.cookie: str | None = None
```

`Browser` is a tiny HTTP client with one cookie. The docstring explains why it sets the `Secure` cookie by hand: a plain-HTTP client rightly refuses to send a Secure cookie, whereas real browsers treat `http://localhost` as secure.

```python
    def request(
        self,
        method: str,
        path: str,
        *,
        form: dict[str, str] | None = None,
        body: object = None,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        """Send one request and remember a cookie the server sets or clears."""
```

`request` sends one request. The `*` makes `form`, `body` and `headers` keyword-only.

```python
        sent = dict(headers or {})
        payload: str | None = None
        if form is not None:
            payload = urlencode(form)
            sent["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            payload = json.dumps(body)
            sent["Content-Type"] = "application/json"
            sent["Accept"] = "application/json"
```

It copies the headers; a `form` is URL-encoded with the form content type; a `body` is JSON-encoded and the request is marked as JSON in both directions.

```python
        if self.cookie:
            sent["Cookie"] = f"{SESSION_COOKIE}={self.cookie}"
```

If it holds a cookie, the `Cookie` header is added.

```python
        connection = http.client.HTTPConnection(self._host, self._port, timeout=10)
        try:
            connection.request(method, path, body=payload, headers=sent)
            response = connection.getresponse()
            text = response.read().decode()
            cookies = tuple(value for name, value in response.getheaders() if name.lower() == "set-cookie")
            reply = Reply(response.status, dict(response.getheaders()), cookies, text)
        finally:
            connection.close()
```

It opens a connection with a 10-second limit, sends the request, reads the answer, collects all `Set-Cookie` headers and builds a `Reply`; `finally` always closes the connection.

```python
        for header in reply.set_cookies:
            name, _, rest = header.partition("=")
            if name == SESSION_COOKIE:
                self.cookie = None if "Max-Age=0" in header else rest.split(";", 1)[0]
        return reply
```

For each `Set-Cookie` of the session cookie, the client remembers the value (the part before the first `;`), or forgets it if the server expired it with `Max-Age=0`.

```python
    def csrf_token(self) -> str:
        """The current session's CSRF token, read from the sign-in form."""
        match = _CSRF_FIELD.search(self.request("GET", "/login").body)
        if match is None:
            raise RuntimeError("no CSRF token on the sign-in page")
        return match.group(1)
```

`csrf_token` loads the sign-in page and reads the token from the hidden form field; a missing token raises an error.

```python
    def register(self, prefix: str) -> tuple[str, str, Reply]:
        """Sign up and sign in a new generated user; returns the username, the password and the sign-in reply."""
        username, password = f"{prefix}_{secrets.token_hex(4)}", secrets.token_urlsafe(18)
        self.request(
            "POST", "/signup", form={"username": username, "password": password, "csrf_token": self.csrf_token()}
        )
        signed_in = self.request(
            "POST", "/login", form={"username": username, "password": password, "csrf_token": self.csrf_token()}
        )
        return username, password, signed_in
```

`register` makes a username with a prefix and four random bytes in hexadecimal and an 18-byte random password, signs up with the CSRF token, signs in and returns the name, the password and the sign-in reply.

```python
    def api(self, method: str, path: str, body: object = None, *, csrf: str | None = "auto") -> Reply:
        """A JSON request with the session's CSRF token (``"auto"``), none (``None``) or a given one."""
        token = self.csrf_token() if csrf == "auto" else csrf
        return self.request(method, path, body=body, headers={CSRF_HEADER: token} if token else {})
```

`api` sends a JSON request. The `csrf` argument is `"auto"` (fetch the session's token), `None` (send none) or a given text; the token goes in the CSRF header.

```python
def _cookie_flags(set_cookies: tuple[str, ...]) -> tuple[bool, str]:
    cookie = next((value for value in set_cookies if value.startswith(f"{SESSION_COOKIE}=")), "")
    value = cookie.split("=", 1)[1].split(";", 1)[0] if cookie else ""
    flags = all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/"))
    opaque = len(value) >= 40 and value.count(".") < 2
    return flags and opaque, f"{cookie.split(';', 1)[0][:24]}... ({len(value)} chars) " + "; ".join(
        part.strip() for part in cookie.split(";")[1:]
    )
```

`_cookie_flags` finds the session cookie in the replies and checks it has `HttpOnly`, `Secure`, `SameSite=Lax` and `Path=/`, and that its value is opaque (at least 40 characters and not a signed token with dots). It returns the verdict and a readable description with only the first 24 characters of the value shown.

```python
def run_scenario(host: str, port: int) -> list[Step]:
    """Run every step against the server and return the results. Never raises on a failed expectation."""
    alice, bob, steps = Browser(host, port), Browser(host, port), []
```

`run_scenario` runs every step and returns the results without ever raising on a failed expectation. It creates two browsers, Alice's and Bob's.

```python
    def check(name: str, passed: bool, detail: str) -> None:
        steps.append(Step(name, passed, detail))
```

`check` appends a `Step`.

```python
    ready = alice.request("GET", "/readyz")
    check("the server is ready", ready.status == 200, f"/readyz -> {ready.status}")
```

Step 1: `/readyz` answers 200.

```python
    _, _, signed_in = alice.register("alice")
    bob_name, bob_password, _ = bob.register("bob")
    ok, detail = _cookie_flags(signed_in.set_cookies)
    check("the session cookie is opaque, HttpOnly, Secure, SameSite=Lax", ok, detail)
```

Step 2: both users sign up and sign in; the cookie flags are checked on Alice's sign-in reply.

```python
    page = alice.request("GET", "/notes")
    missing = [name for name in REQUIRED_HEADERS if name not in page.headers]
    check("security headers are on the response", not missing, f"missing: {missing or 'none'}")
```

Step 3: the notes page has the three required headers.

```python
    created = alice.api("POST", "/notes", {"title": "It's a title", "content": HOSTILE})
    note_id = int(str(created.json().get("id", 0)))
    note_page = alice.request("GET", f"/notes/{note_id}").body
    check(
        "hostile content is stored and rendered as inert text",
        created.status == 201 and "&lt;script&gt;" in note_page and "<script>" not in note_page,
        f"note {note_id}: page shows the markup escaped",
    )
```

Step 4: Alice creates a note whose content is the hostile text; the page must show `&lt;script&gt;` (encoded) and must not contain a real `<script>` tag.

```python
    verdicts = [
        bob.api(method, f"/notes/{note_id}", body, csrf="auto").status
        for method, body in (("GET", None), ("PATCH", {"content": "changed"}), ("DELETE", None))
    ]
    check(
        "another user gets 404 for read, update and delete",
        verdicts == [404, 404, 404],
        f"GET, PATCH, DELETE -> {verdicts}",
    )
```

Step 5: Bob (with a valid CSRF token) tries to read, update and delete Alice's note; each answer must be 404.

```python
    no_token = alice.api("POST", "/notes", {"title": "x", "content": "y"}, csrf=None)
    wrong_token = alice.api("DELETE", f"/notes/{note_id}", csrf="not-the-token")
    check(
        "a state-changing request without the CSRF token is refused",
        (no_token.status, wrong_token.status) == (403, 403),
        f"no token -> {no_token.status}, wrong token -> {wrong_token.status}",
    )
```

Step 6: Alice sends a create without a token and a delete with a wrong token; both must be 403.

```python
    attempts = [
        bob.request(
            "POST",
            "/login",
            form={"username": bob_name, "password": bob_password[::-1], "csrf_token": bob.csrf_token()},
        )
        for _ in range(6)
    ]
    codes = [attempt.status for attempt in attempts]
    check(
        "repeated wrong passwords are throttled",
        codes[:5] == [401] * 5 and codes[5] == 429,
        f"statuses {codes}, Retry-After {attempts[-1].headers.get('Retry-After', 'missing')} s",
    )
```

Step 7: Bob sends six sign-ins with his password reversed (wrong); the first five must be 401 and the sixth 429, and the `Retry-After` value is shown.

```python
    old_cookie = alice.cookie
    alice.request("POST", "/logout", form={"csrf_token": alice.csrf_token()})
    replay = Browser(host, port)
    replay.cookie = old_cookie
    after = replay.request("GET", "/notes", headers={"Accept": "application/json"})
    check(
        "the old session id stops working after sign out",
        after.status == 401,
        f"GET /notes with the old cookie -> {after.status}",
    )
```

Step 8: Alice's cookie is saved, she logs out, and a fresh client with the old cookie asks for `/notes`; the answer must be 401, so the old session id is dead.

```python
    return steps
```

The list of steps is returned.

```python
def main(argv: list[str] | None = None, *, out: Callable[[str], None] = print) -> int:
    """Run the scenario against ``--host``/``--port`` (default: APP_HOST and APP_PORT) and print one line per step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("APP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8047")))
    args = parser.parse_args(argv)
```

`main` takes the arguments and an output function. The options `--host` and `--port` default to the environment variables.

```python
    steps = run_scenario(args.host, args.port)
    for number, step in enumerate(steps, start=1):
        out(f"{number:>2}. {'PASS' if step.passed else 'FAIL'}  {step.name}\n        {step.detail}")
    failed = [step for step in steps if not step.passed]
    out(f"{len(steps) - len(failed)} of {len(steps)} checks passed")
    return 1 if failed else 0
```

It runs the scenario, prints one numbered PASS or FAIL line with the detail per step, prints the count and returns 1 if any step failed.

```python
if __name__ == "__main__":
    sys.exit(main())
```

When run as a program, the return value is the exit code.

### Line by line: `scripts/prove_controls.py`

```python
"""Prove each control by removing it: run the tests that guard it with the matching deliberate weakness switched on
and require every one of them to fail. A first run without any weakness requires them all to pass, so a failure
later means "this test notices the missing control", not "this test is broken".

    make prove          (needs make up)

The weaknesses are the UNSAFE_* settings; the app accepts them only under APP_ENV=test, which this script sets.
"""
```

The docstring: the script proves each control by removing it. It runs the tests that guard a control with the matching deliberate weakness switched on and requires every one of them to fail. A first run without any weakness requires them all to pass, so a later failure means "this test notices the missing control", not "this test is broken". `make prove` needs `make up`. The weaknesses are the `UNSAFE_*` settings, accepted only under `APP_ENV=test`, which the script sets.

```python
from __future__ import annotations

import os
import subprocess
import sys
```

Type hints kept as text; `os`, `subprocess` (starts other programs) and `sys`.

```python
SECURITY = "tests/security"
# weakness setting -> the tests that must fail while it is on (the control it removes, as the threat model names it)
GUARDS: dict[str, tuple[str, ...]] = {
    "UNSAFE_WEAK_PASSWORD_HASH": (f"{SECURITY}/test_passwords.py::test_passwords_are_salted_and_not_logged",),
    "UNSAFE_SQL_CONCATENATION": (f"{SECURITY}/test_injection.py::test_hostile_content_is_stored_exactly_as_text",),
    "UNSAFE_RAW_NOTE_OUTPUT": (f"{SECURITY}/test_injection.py::test_hostile_content_is_rendered_as_inert_text",),
    "UNSAFE_SKIP_OWNERSHIP_CHECK": (
        f"{SECURITY}/test_authorization.py::test_user_a_cannot_read_update_or_delete_user_b_note",
        f"{SECURITY}/test_authorization.py::test_changing_the_id_in_the_url_reaches_no_note_of_another_user",
        f"{SECURITY}/test_authorization.py::test_a_user_the_note_is_shared_with_can_read_but_not_change_or_share_it",
    ),
    "UNSAFE_WEAK_SESSION_COOKIE": (f"{SECURITY}/test_session.py::test_session_cookie_flags",),
    "UNSAFE_SKIP_CSRF": (
        f"{SECURITY}/test_session.py::test_state_changing_request_without_csrf_token_is_refused",
        f"{SECURITY}/test_session.py::test_another_sessions_csrf_token_does_not_work",
    ),
    "UNSAFE_SKIP_SECURITY_HEADERS": (f"{SECURITY}/test_session.py::test_security_headers_on_every_response",),
}
```

`SECURITY` is the folder of the security tests. `GUARDS` is a dictionary from each weakness setting to the tuple of tests that must fail while it is on. Each test is named in pytest's **node id** form `file::function`. For example `UNSAFE_SKIP_OWNERSHIP_CHECK` is guarded by three authorization tests, `UNSAFE_SKIP_CSRF` by two session tests and the other five weaknesses by one test each.

```python
def run_pytest(node_ids: tuple[str, ...], weakness: str | None) -> dict[str, str]:
    """Run the given tests and return {test name: passed | failed}, read from pytest's ``-rA`` summary lines."""
```

`run_pytest` runs the given tests with or without a weakness and returns a dictionary from test name to `passed` or `failed`.

```python
    env = {key: value for key, value in os.environ.items() if not key.startswith("UNSAFE_")}
    env["APP_ENV"] = "test"
    if weakness:
        env[weakness] = "1"
```

It copies the current environment without any `UNSAFE_*` variable (so a leftover switch cannot disturb the baseline), sets `APP_ENV=test` and, if a weakness is named, sets it to `1`.

```python
    run = subprocess.run(
        [sys.executable, "-m", "pytest", *node_ids, "-q", "-p", "no:cacheprovider", "-rA", "--tb=no"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
```

It starts pytest with the same Python (`sys.executable -m pytest`) and the node ids; `-q` quiet, `-p no:cacheprovider` writes no cache folder, `-rA` prints a summary line for every outcome, `--tb=no` leaves out stack traces. Output is captured as text and a failing exit code does not raise (`check=False`).

```python
    outcomes = {}
    for line in run.stdout.splitlines():
        status, _, rest = line.partition(" ")
        if status in {"PASSED", "FAILED", "ERROR"} and "::" in rest:
            outcomes[rest.split("::")[-1].split(" ")[0]] = "passed" if status == "PASSED" else "failed"
    return outcomes
```

It reads the summary lines: a line starting with `PASSED`, `FAILED` or `ERROR` and containing `::` gives the test function name (the part after the last `::`, before any space) and its outcome.

```python
def main() -> int:
    """Print the table of weaknesses and verdicts; return 1 when a control is not proven."""
```

`main` prints the table and returns 1 when a control is not proven.

```python
    every_guard = tuple(dict.fromkeys(node for nodes in GUARDS.values() for node in nodes))
    baseline = run_pytest(every_guard, None)
    broken = [name for name, outcome in baseline.items() if outcome != "passed"]
    print(f"baseline, no weakness: {len(baseline) - len(broken)} of {len(baseline)} guarding tests pass")
```

`dict.fromkeys(...)` removes duplicates while keeping order, giving every guarding test once. The baseline run (no weakness) is printed as a count.

```python
    if broken or len(baseline) != len(every_guard):
        print(f"FAIL: these must pass with every control in place: {broken or 'some tests did not run'}")
        return 1
```

If any baseline test did not pass, or fewer ran than expected, the script prints a failure and stops with 1.

```python
    unproven = 0
    for weakness, nodes in GUARDS.items():
        outcomes = run_pytest(nodes, weakness)
        for node in nodes:
            name = node.split("::", 1)[1]
            verdict = (
                "FAILS without the control (proven)" if outcomes.get(name) == "failed" else "STILL PASSES (not proven)"
            )
            unproven += outcomes.get(name) != "failed"
            print(f"{weakness:<30} {name}\n{'':<30} -> {verdict}")
```

For each weakness it runs its tests with the weakness on. A test whose outcome is `failed` is "FAILS without the control (proven)"; anything else is "STILL PASSES (not proven)", counted in `unproven`.

```python
    total = sum(len(nodes) for nodes in GUARDS.values())
    print(f"{total - unproven} of {total} guarding tests fail when their control is removed")
    return 1 if unproven else 0
```

The total is printed (for example "9 of 9 guarding tests fail when their control is removed") and the exit code is 1 if any was unproven.

```python
if __name__ == "__main__":
    sys.exit(main())
```

When run as a program, the return value is the exit code.

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
