# mypy 2.4

## What it is

mypy is a **static type checker** for Python. Python lets you write **type hints** (`def f(x: int) -> str:`) but ignores them when running. mypy reads those hints without running the program and reports where the code contradicts them: calling a function with the wrong kind of value, using a value that might be `None`, or forgetting to annotate. Pinned: `mypy==2.4.0`.

## Why this repository uses it

Many security bugs are "I assumed this was there": a `None` from a database lookup used as a user, a string where an integer was expected. With `strict = true` mypy forces every `User | None` to be handled before use, and checks that adapters really implement the `Protocol` ports (`tech/python.md`). It is part of `make lint`.

## Where it appears

| Path | What it does with mypy |
| --- | --- |
| `pyproject.toml` `[tool.mypy]`, `[[tool.mypy.overrides]]` | Configuration. |
| `Makefile` (`lint`) | Runs `mypy` with no arguments, so it uses `files = ["src", "tests", "scripts"]`. |
| Type hints throughout `src/` | What mypy checks. |
| `# type: ignore[...]` comments | The few places where a hint is intentionally overridden. |

## How it works underneath

1. mypy parses all listed files and builds a model of every function, class and variable and the types they hold.
2. It follows values through the code: after `if user is None: return`, it knows `user` is a `User` in the rest of the function.
3. For a `Protocol`, it checks "does this class have every method with a compatible signature?". No inheritance is needed.
4. It caches results in a `.mypy_cache` folder so later runs are fast.
5. It prints `file:line: error: message [code]` for each problem and exits 1 if there are any.

### Ideas you need first

- **A type.** The kind of a value: whole number (`int`), text (`str`), true/false (`bool`), a list of numbers (`list[int]`), "a `User` or nothing" (`User | None`). Knowing the type tells you what you may do with the value: you can call `.upper()` on text but not on a number.
- **A type hint.** A label you write in the code (`def find(user_id: int) -> User | None:`) saying what goes in and what comes out. Python runs the program the same with or without them.
- **A static check.** Looking for mistakes by reading the code without running it. mypy reads the hints and the code and reports places where they disagree, such as passing text where a number is expected, or using a value that might be `None`.
- **`Any`.** The type that means "anything goes". Where mypy meets `Any` it stops checking. Strict mode is mostly about not letting `Any` creep in.

## Walkthrough of this repository's use

```toml
[tool.mypy]
python_version = "3.12"
strict = true
files = ["src", "tests", "scripts"]
```
`strict = true` is a bundle of options: every function must be annotated (`disallow_untyped_defs`), no implicit `Any` leaks (`warn_return_any`), no unused `# type: ignore`, optional values must be handled (`strict_optional`), and more. `files` lets plain `mypy` check the three folders.

```toml
[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
```
Test functions are allowed to be unannotated (pytest passes fixtures by name). Everything else is still checked.

### Patterns you will see in the source

- **Rows from the database are `tuple[object, ...]`.** mypy will not let you treat `object` as an `int`, so the repositories convert explicitly: `int(str(row[0]))`, `str(row[2])`, and a helper `_timestamp(value)` that asserts `isinstance(value, datetime)` (with a `noqa: S101` explaining why). That keeps the type honest without scattering `Any`.
- **`Protocol` ports.** `PostgresUserRepository` is passed to `AccountService(users: UserRepository, ...)` in `composition.py`. If a method signature drifts, mypy reports it right there.
- **`X | None` returns.** `by_username(...) -> User | None` forces a check; `AccountService._find` returns `None` when validation fails, and `authenticate` handles both `None` and a wrong password in one `if`.
- **`Literal`** for the environment: `AppEnv = Literal["development", "test", "production"]`, so a typo like `"prod"` is caught.
- **`from __future__ import annotations`** makes hints lazy so forward references work.
- **The ignore comments.** `# type: ignore[method-assign]` on the `ProxyFix` wrapping in `app.py` (reassigning `app.wsgi_app` is the documented pattern); `# type: ignore[arg-type]` in `tests/unit/test_http_app.py` where a tiny `FakeDatabase` stands in for `Database`. Each names the exact error code, so it cannot hide a different problem.

### Why `--strict` and not just default

Without strict mode, an unannotated function is treated as "anything goes" and mypy checks nothing inside it. The layered design (ports with precise signatures) only pays off when every adapter is checked against them.

### What `strict = true` switches on

`strict = true` in `[tool.mypy]` turns on this list of checks (the list is printed by `mypy --help` for the pinned version 2.4.0):

| Check | What it refuses |
| --- | --- |
| `disallow_any_generics` | A bare `list` or `dict` with no contents type; you must write `list[int]`, `dict[str, str]`. |
| `disallow_subclassing_any` | A class that inherits from something whose type is `Any`. |
| `disallow_untyped_calls` | Calling a function that has no type hints from code that has them. |
| `disallow_untyped_defs` | A function without hints for every parameter and its return value. |
| `disallow_incomplete_defs` | A function with hints on some parameters and not others. |
| `check_untyped_defs` | (Positive) Also check the inside of functions that lack hints. |
| `disallow_untyped_decorators` | A decorator with no hints, which would hide the type of what it wraps. |
| `warn_redundant_casts` | A `cast(...)` that changes nothing. |
| `warn_unused_ignores` | A `# type: ignore` comment that no longer silences anything. |
| `warn_return_any` | Returning an `Any` value from a function declared to return something specific. |
| `no_implicit_reexport` | Importing a name from a module that merely imported it itself. |
| `strict_equality` | Comparing values of types that can never be equal. |
| `extra_checks` | A few additional correctness checks. |

The other keys in the repository's `[tool.mypy]` table: `python_version = "3.12"` (check as if running on that version); `files = ["src", "tests", "scripts"]` (what plain `mypy` with no arguments checks). `[[tool.mypy.overrides]]` with `module = ["tests.*"]` relaxes three flags for the tests only: `disallow_untyped_defs`, `disallow_incomplete_defs` and `disallow_untyped_calls` are set to false, because pytest hands fixtures to test functions by name and annotating them adds nothing.

**`# type: ignore[code]`.** Tells mypy to skip one error on one line. The bracket names the error (`method-assign`, `arg-type`); a bare `# type: ignore` would hide any error on the line, so the repository never writes one. Two exist: the `ProxyFix` wrapping in `app.py`, and a fake in `tests/unit/test_http_app.py`.

**How to read mypy's output.** `path:line: error: message [code]`, for example `src/notes_app/interfaces/composition.py:65: error: Argument 2 to "NoteService" has incompatible type "PostgresUserRepository"; expected "UserRepository" [arg-type]`, then notes saying which protocol member is missing. It exits 1 when there is any error, so `make lint` fails.

## Try it yourself

1. Run the checker:
   ```bash
   .venv/bin/mypy
   ```
   Expect `Success: no issues found in 68 source files`.
2. Make mypy catch a real mistake on a scratch file:
   ```bash
   printf 'def f(x: int) -> int:\n    return x.upper()\n\ndef g(x):\n    return x\n' > /tmp/t.py
   .venv/bin/mypy --strict /tmp/t.py
   ```
   Expect `"int" has no attribute "upper"  [attr-defined]` and `Function is missing a type annotation  [no-untyped-def]`. (Delete `/tmp/t.py`.)
3. Break a port on purpose (then revert): rename `by_username` to `find_by_name` in `src/notes_app/infrastructure/postgres/users.py` and run `.venv/bin/mypy`. Expect an error in `composition.py` saying the argument has an incompatible type and listing the missing protocol member. Restore with `git checkout src/notes_app/infrastructure/postgres/users.py`.
4. See which ignores exist:
   ```bash
   grep -rn "type: ignore" src tests scripts
   ```
   Expect two lines: the `ProxyFix` one in `app.py` and the `FakeDatabase` one in `tests/unit/test_http_app.py`.

## Mistakes people make

- Sprinkling `Any` or bare `# type: ignore` until the output is quiet. Here each ignore names its code.
- Trusting hints at run time. Python does not enforce them. The repository validates input at runtime in `domain/validation.py` as well.
- Annotating with `dict` or `list` without contents. The code writes `dict[str, str]`, `tuple[object, ...]`.
- Skipping mypy in CI because it is slower than ruff. It is part of `make check`.

## Check yourself

1. Does Python check type hints when the program runs?
   *No; only tools like mypy do.*
2. What does `X | None` force you to do?
   *Handle the `None` case before using the value.*
3. How does mypy check a `Protocol`?
   *By matching method names and signatures; no inheritance is needed.*
4. Why are test functions allowed to be unannotated?
   *pytest fills parameters by fixture name; the override relaxes only the `tests.*` modules.*
5. What does `# type: ignore[arg-type]` ignore?
   *Only an `arg-type` error on that line.*

## Further reading

- mypy documentation: https://mypy.readthedocs.io/en/stable/
- Strict mode: https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict
- Protocols: https://mypy.readthedocs.io/en/stable/protocols.html
- Typing reference (Python 3.12): https://docs.python.org/3.12/library/typing.html
