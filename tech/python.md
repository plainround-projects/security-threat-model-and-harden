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
