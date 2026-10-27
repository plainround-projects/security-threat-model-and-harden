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
