# pyproject.toml packaging and setuptools 75

## What it is

**Packaging** is turning a folder of Python files into something `pip` can install: it needs a name, a version, a list of dependencies, which files to include and which commands to create. In modern Python all of that is declared in `pyproject.toml` (format: `tech/toml.md`). **setuptools** is the long-standing **build backend**: the program that reads that metadata and builds the installable thing (a **wheel**, a zip file with a `.whl` name). The `[build-system]` table names the backend; `pip` downloads it, runs it, then installs the wheel. `setuptools>=75` is the requirement; the Docker image's own copy is removed after the install.

## Why this repository uses it

The code lives under `src/notes_app/` (the "src layout"). Installing the project (`pip install -e .` locally, `pip install --no-deps .` in Docker) is what makes `import notes_app` work from anywhere and what creates the two commands `notes-app-health` and `notes-app-demo`. The src layout also stops tests from accidentally importing the working copy instead of the installed one.

## Where it appears

| Path | What it does |
| --- | --- |
| `pyproject.toml` `[build-system]`, `[project]`, `[project.scripts]`, `[tool.setuptools.*]` | Metadata, commands, package discovery, bundled files. |
| `Makefile` | `pip install --no-deps -e .` in the stamp rule. |
| `Dockerfile` | `COPY pyproject.toml README.md ./`, `COPY src ./src`, `RUN pip install --no-deps .`. |
| `src/security_threat_model_and_harden.egg-info/` | Generated metadata folder left by an editable install; ignored by git (`*.egg-info/`). |

## How it works underneath

1. `pip install .` reads `[build-system]`, creates a temporary isolated environment, installs `setuptools>=75` there, and asks it to build a wheel from the project folder.
2. setuptools reads `[project]` for the metadata, finds the packages to include, and writes the wheel.
3. pip unpacks the wheel into the environment's `site-packages` and writes small launcher programs for `[project.scripts]` into `.venv/bin/`.
4. An **editable** install (`-e`) instead drops a link, so Python imports straight from `src/`; edits apply at once.

### Ideas you need first

- **A package and an installer.** A package is code bundled so others can install it. `pip` is Python's installer; it reads a project's description, installs its dependencies and makes its commands available.
- **A build backend.** The program pip runs to turn the source folder into an installable file (a **wheel**). `setuptools` is one.
- **An entry point.** A name that becomes a command: `stock-service-health = "stock_service.interfaces.health_cli:main"` creates a program that calls that function.
- **Editable install.** `pip install -e .` links the installed project to the source folder, so edits apply without reinstalling.

## Walkthrough of this repository's use

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```
`requires` is what the build needs. `build-backend` is the Python object pip calls.

```toml
[project]
name = "security-threat-model-and-harden"
version = "0.1.0"
description = "..."
readme = "README.md"
requires-python = ">=3.12"
```
Name, version, a one-line description, the README shown on a package page, and the oldest Python allowed. Installing on 3.11 fails with a clear message. That is why the `Dockerfile` copies `README.md`: the build reads it.

```toml
[tool.setuptools.packages.find]
where = ["src"]
```
Look for packages (folders with `__init__.py`) under `src/` only. Without this, setuptools might include `tests/` or `scripts/`.

```toml
[tool.setuptools.package-data]
"notes_app.interfaces.http" = ["templates/*.html", "static/*.css"]
```
By default only `.py` files are packaged. The HTML templates and the stylesheet are not Python, so this line names them. Without it the container would start and then fail with "TemplateNotFound" on the first page. (A good reason for the container health check and the e2e test.)

```toml
[project.scripts]
notes-app-health = "notes_app.interfaces.health_cli:main"
notes-app-demo = "notes_app.interfaces.demo_cli:main"
```
Creates two commands. `module:function` is what the launcher calls; the function's return value becomes the exit code.

### Order in the Dockerfile and why `--no-deps`

The dependencies are installed first from the hashed lock; the project is installed second with `--no-deps`, so pip cannot reach out to resolve anything or pull an unreviewed package.

### Every dependency, and what its version text means

A version rule such as `flask>=3.1,<4` means "any version from 3.1 up to but not including 4": the lower bound is the oldest release known to work, the upper bound avoids a future major release that may break things. `psycopg[binary,pool]>=3.2,<4` also asks for two **extras**: optional add-on packages the library defines (`binary`: a precompiled database client library, so no compiler is needed; `pool`: the connection-pool package).

| Where | Package | Role in this repository |
| --- | --- | --- |
| `dependencies` (shipped) | `flask>=3.1,<4` | The web framework (`tech/flask.md`). |
| | `gunicorn>=23,<26` | The production web server (`tech/gunicorn.md`). |
| | `psycopg[binary,pool]>=3.2,<4` | The PostgreSQL driver and its pool (`tech/psycopg.md`). |
| | `argon2-cffi>=23.1,<26` | Password hashing (`tech/argon2.md`). |
| `dev` extra | `pytest>=8,<10`, `pytest-cov>=5` | Test runner and coverage (`tech/pytest.md`). |
| | `httpx>=0.27,<1` | An HTTP client that nothing imports (`tech/httpx.md`). |
| | `ruff>=0.6`, `mypy>=1.11` | Linting and type checking. |
| | `import-linter>=2.0` | Architecture rules. |
| | `pip-audit>=2.7` | Vulnerability check on dependencies. |
| | `cyclonedx-bom>=5,<8` | The bill of materials writer. |

**Every key in `[project]`:** `name` (the name pip shows); `version` (`0.1.0`: major.minor.patch); `description`; `readme` (the file shown as the long description, and the reason the Dockerfile copies `README.md`); `requires-python = ">=3.12"`; `license = { text = "MIT" }`; `authors`; `dependencies`. `[project.optional-dependencies]` defines the `dev` extra: `pip install .[dev]` (or the lock compile with `--extra dev`) adds those packages. `[project.scripts]` creates two commands. `[tool.setuptools.packages.find]` with `where = ["src"]` and `[tool.setuptools.package-data]` are explained above. `[build-system]` names `setuptools>=75` as the builder.

**What "editable install" does.** `pip install -e .` does not copy the code into the environment. It records a link to `src/`, so edits are used immediately. The metadata folder `src/security_threat_model_and_harden.egg-info/` is what pip reads to know the project's name, version and commands; it is regenerated and ignored by git.

### Line by line: `pyproject.toml`

`pyproject.toml` is the project's main settings file in TOML (`tech/toml.md`). `[name]` starts a **table** (a group of settings); `[[name]]` adds one item to a list of tables.

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```

`[build-system]` says how pip builds the project: `setuptools` version 75 or newer, through `setuptools.build_meta`.

```toml
[project]
name = "security-threat-model-and-harden"
version = "0.1.0"
description = "A notes app, threat-modeled with STRIDE and hardened control by control, with one test per control that fails when the control is removed."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [{ name = "Sumit Srivastava" }]
```

`[project]` is the standard metadata: name, version, a description, the readme file, `requires-python = ">=3.12"`, license and authors.

```toml
dependencies = [
    "flask>=3.1,<4",
    "gunicorn>=23,<26",
    "psycopg[binary,pool]>=3.2,<4",
    "argon2-cffi>=23.1,<26",
]
```

`dependencies` is what the app needs to run, each with a **version range** (`flask>=3.1,<4` is 3.1 or newer but below 4). `psycopg[binary,pool]` asks for two **extras**: a ready-made compiled client library and the pool package. `argon2-cffi` hashes passwords.

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8,<10",
    "pytest-cov>=5",
    "httpx>=0.27,<1",
    "ruff>=0.6",
    "mypy>=1.11",
    "import-linter>=2.0",
    "pip-audit>=2.7",
    "cyclonedx-bom>=5,<8",
]
```

`[project.optional-dependencies]` defines the group `dev`, installed with `pip install -e ".[dev]"`: `pytest` and `pytest-cov` (tests, coverage), `httpx` (an HTTP client pinned for tests), `ruff` (lint and format), `mypy` (types), `import-linter` (layer rules), `pip-audit` (vulnerable dependencies) and `cyclonedx-bom` (SBOM).

```toml
[project.scripts]
notes-app-health = "notes_app.interfaces.health_cli:main"
notes-app-demo = "notes_app.interfaces.demo_cli:main"
```

`[project.scripts]` creates commands: installing the project puts `notes-app-health` and `notes-app-demo` in the environment's `bin/` folder, each calling the named function.

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

`[tool.setuptools.packages.find]` with `where = ["src"]` looks for packages inside `src/` (the **src layout**).

```toml
[tool.setuptools.package-data]
"notes_app.interfaces.http" = ["templates/*.html", "static/*.css"]
```

`package-data` includes the template and CSS files in the installed package; without it, setuptools would copy only Python files.

```toml
[tool.ruff]
line-length = 120
target-version = "py312"
src = ["src", "tests", "scripts"]
```

`[tool.ruff]`: line length 120, Python 3.12 syntax, and `src` lists the folders of the project's own code for import sorting.

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "N", "C4", "RUF", "PT", "S", "DTZ", "D100", "D101", "D103", "D104"]
```

`[tool.ruff.lint]` selects rule families: `E` style errors, `F` mistakes such as unused names, `I` import order, `B` likely bugs, `UP` outdated syntax, `SIM` simplifications, `N` naming, `C4` comprehensions, `RUF` ruff's own rules, `PT` pytest style, `S` security rules, `DTZ` datetimes without time zones, and the docstring rules `D100` module, `D101` class, `D103` function and `D104` package.

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["D", "S101", "S105", "S106", "S608"]
"scripts/**" = ["D", "S603", "S607"]
```

`per-file-ignores`: tests may skip docstrings, use `assert` (`S101`), hold password-looking strings (`S105`, `S106`) and build SQL text (`S608`); scripts may skip docstrings and start subprocesses (`S603`, `S607`).

```toml
[tool.mypy]
python_version = "3.12"
strict = true
files = ["src", "tests", "scripts"]
```

`[tool.mypy]`: Python 3.12, `strict = true` and the folders to check.

```toml
[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
```

`[[tool.mypy.overrides]]` relaxes three checks for `tests.*` only: untyped functions, partly typed functions and calls of untyped functions are allowed.

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
```

`[tool.pytest.ini_options]`: `testpaths`, and `addopts` of `-ra` (summarize everything that did not pass) and `--strict-markers` (unknown markers are errors).

```toml
markers = [
    "integration: needs PostgreSQL from docker-compose.yml (make up)",
    "security: one test per control of the threat model; needs PostgreSQL (make up)",
    "e2e: the lesson's scenario over real HTTP against a running server; needs PostgreSQL (make up)",
]
```

`markers` registers three labels, `integration`, `security` and `e2e`, each with a description.

```toml
[tool.coverage.run]
source = ["notes_app"]
branch = true
```

`[tool.coverage.run]` measures `notes_app` with branch coverage (`branch = true` counts each side of an `if`).

```toml
[tool.coverage.report]
show_missing = true
skip_covered = false
```

`[tool.coverage.report]`: list missing line numbers; do not hide covered files.

```toml
[tool.importlinter]
root_package = "notes_app"
include_external_packages = true
```

`[tool.importlinter]`: the package to analyze, and `include_external_packages = true` so rules can name third-party packages.

```toml
[[tool.importlinter.contracts]]
name = "Layers: interfaces -> infrastructure -> application -> domain, never upward"
type = "layers"
layers = [
    "notes_app.interfaces",
    "notes_app.infrastructure",
    "notes_app.application",
    "notes_app.domain",
]
```

The first contract is a `layers` contract: listed from the highest to the lowest, each layer may import only layers below it. Interfaces may import infrastructure, application and domain; domain imports none.

```toml
[[tool.importlinter.contracts]]
name = "Domain and application know nothing about Flask, PostgreSQL or the hashing library"
type = "forbidden"
source_modules = ["notes_app.domain", "notes_app.application"]
forbidden_modules = ["flask", "werkzeug", "jinja2", "psycopg", "psycopg_pool", "argon2"]
```

A `forbidden` contract: the domain and application layers may not import Flask, Werkzeug, Jinja2, psycopg, psycopg_pool or argon2. The rules of the program stay independent of web, database and hashing libraries.

## Try it yourself

1. See the installed commands:
   ```bash
   ls .venv/bin | grep notes-app
   ```
   Expect `notes-app-demo` and `notes-app-health`.
2. See the metadata pip recorded:
   ```bash
   .venv/bin/pip show security-threat-model-and-harden
   ```
   Expect `Name: security-threat-model-and-harden`, `Version: 0.1.0`, `Requires: argon2-cffi, flask, gunicorn, psycopg`, and an `Editable project location`.
3. Confirm the templates are packaged (a wheel build; needs network the first time because of build isolation):
   ```bash
   .venv/bin/pip wheel --no-deps -w /tmp/whl . -q && unzip -l /tmp/whl/*.whl | grep -E "templates|static"; rm -rf /tmp/whl
   ```
   Expect the five `templates/*.html` files and `static/style.css` in the listing.
4. Ask where Python imports the package from:
   ```bash
   .venv/bin/python -c "import notes_app; print(notes_app.__file__)"
   ```
   Expect a path ending `src/notes_app/__init__.py`.

## Mistakes people make

- Forgetting `package-data`: templates missing from the built package.
- Importing from the repository root because the working directory is on the path, so tests pass while the installed package is broken. The src layout and the Docker build catch it.
- Mixing `setup.py`, `setup.cfg` and `pyproject.toml`. This project uses only the last.
- Pinning the project's own dependencies exactly in `pyproject.toml`. Ranges go there; exact versions go in the lock files (`tech/uv-and-lock-files.md`).
- Committing `*.egg-info/` or `build/`. Both are in `.gitignore`.

## Check yourself

1. What is a wheel?
   *A built, ready-to-unpack package file (`.whl`).*
2. What does the `src` layout protect against?
   *Accidentally importing the source folder instead of the installed package.*
3. Why list the templates in `package-data`?
   *Only `.py` files are packaged by default.*
4. What does `[project.scripts]` create?
   *Commands in `.venv/bin` that call a Python function and use its return value as the exit code.*
5. Why is the project installed with `--no-deps` in Docker?
   *Its dependencies came from the hashed lock; nothing else should be resolved.*

## Further reading

- Python Packaging User Guide: https://packaging.python.org/en/latest/
- `pyproject.toml` specification: https://packaging.python.org/en/latest/specifications/pyproject-toml/
- setuptools documentation: https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html
- Src layout vs flat layout: https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/
