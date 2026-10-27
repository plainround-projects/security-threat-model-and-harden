# Make

## What it is

`make` is a command-line tool that reads a file called `Makefile` and runs recipes from it. A **target** is a name you ask for (`make test`). A **recipe** is the list of shell commands under it. A **prerequisite** is something the target depends on: a file that must exist and be up to date, or another target. `make` was built for compiling programs, but it works as a tidy menu of project commands.

## Why this repository uses it

Every command the lesson asks for is one short word: `make up`, `make test`, `make prove`. The same targets run on a laptop and in CI, so "it works on my machine" and "it works in CI" are the same claim.

## Where it appears

| Path | What it does with Make |
| --- | --- |
| `Makefile` | 22 documented targets, `help` included: set-up (`install`, `env`, `up`, `db`), run (`run`, `demo`, `health`), quality (`lint`, `format`, `test*`, `prove`, `audit`, `sbom`, `check`), containers (`docker-build`, `docker-run`, `down`), `clean`. |
| `.github/workflows/ci.yml` | Calls `make check`, `make audit`, `make sbom`, `make up`, `make test-integration test-security test-e2e`, `make prove`, `make down`. |

The macOS version on this machine is GNU Make 3.81. The Makefile uses only features that version has.

## How it works underneath

1. `make` reads the whole `Makefile`, then looks at the target you named.
2. For a target that is a **file** (like `.venv/.installed`), it compares timestamps: if any prerequisite is newer than the target, or the target is missing, it runs the recipe. Otherwise it says nothing to do.
3. For a **phony** target (not a file, just a name), it always runs. `.PHONY:` lists those names.
4. Each recipe line starts with a **tab** (not spaces) and runs in its own `/bin/sh`. A line that fails stops `make`, unless the line starts with `-`.
5. `@` before a line hides the command echo. `$(NAME)` expands a Make variable; `$$` writes a literal `$` for the shell.

### Ideas you need first

- **A build tool.** A program that runs a list of steps in the right order, and skips steps whose results are already up to date. Programmers use it so that one short command (`make test`) replaces a long sequence they would otherwise have to remember.
- **A target, a prerequisite and a recipe.** In a `Makefile`, `name: other1 other2` followed by indented lines defines a **target** called `name`. `other1` and `other2` are its **prerequisites**: things that must be done first. The indented lines are the **recipe**: shell commands that make runs, one by one, each in its own shell.
- **A file target and a phony target.** If the target name is a real file (like `.venv/.installed`), make runs the recipe only when the file is missing or older than a prerequisite. A **phony** target (listed after `.PHONY:`) is just a name for a job and always runs.
- **A variable.** `NAME := value` stores text; `$(NAME)` uses it. `$@` means "this target's name". A doubled dollar, `$$`, passes a single `$` through to the shell.
- **Tabs.** Recipe lines must start with a Tab character, not spaces.

## Walkthrough of this repository's use

### Variables

```make
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
POSTGRES_USER ?= notes_owner
```
`?=` means "set it only if the caller has not already set it", so `make PYTHON=python3.12 install` works. `:=` assigns once, immediately. `$(shell ...)` runs a shell command while reading the file; `command -v x` prints where `x` is, and `||` tries the next one if it fails.

```make
PSQL := docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 -q
```
A reusable command prefix (see `tech/postgresql.md`): run `psql` inside the `postgres` container, `-T` = no terminal (so redirects work), `-v ON_ERROR_STOP=1` makes `psql` stop at the first SQL error, `-q` = quiet.

```make
-include .env
export
```
`-include` reads `.env` if it exists (the leading `-` ignores a missing file). The bare `export` passes every Make variable, including the ones from `.env`, to every recipe as environment variables. That is how `NOTES_DB_PASSWORD` reaches the application without being written in the Makefile.

### The stamp-file trick

```make
$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file
```
`.venv/.installed` is a real file whose only job is its timestamp. `touch $@` (`$@` = the target's own name) updates it after a successful install. Because it depends on the lock file and `pyproject.toml`, editing either one makes the next `make` target reinstall; otherwise nothing is reinstalled. Targets that need the environment list `$(STAMP)` as a prerequisite. The three commands: create a virtual environment (see `tech/uv-and-lock-files.md`), install exactly the locked, hash-checked packages, install this project itself in editable mode without resolving dependencies again.

### Targets with prerequisites

```make
up: env $(STAMP) ## start PostgreSQL and create the schema, seed and audit table
	docker compose up -d --wait postgres
	@if [ ... ]; then \ ... fi
```
`env` and `$(STAMP)` run first. `docker compose up -d --wait postgres` starts only the database in the background and waits for its health check. The `if` then runs `$(MAKE) --no-print-directory db` only on a fresh database (see `tech/bash.md` for that fragment). `$(MAKE)` is the right way to call make recursively.

### `## comments` and `make help`

The text after `##` on a target line is documentation. The `help` target greps for those lines and prints them. (This note was written after fixing a bug: the first version printed no target names when `.env` existed because `.env` joined `MAKEFILE_LIST` and `grep` started prefixing file names. `grep -h` fixed it.)

### Test targets

```make
test: $(STAMP) ## unit tests with coverage (no database needed)
	$(PY) -m pytest tests/unit --cov=notes_app --cov-report=term
	$(PY) -m coverage report --include='src/notes_app/domain/*,src/notes_app/application/*' --fail-under=95
```
Two commands: run unit tests while measuring coverage, then fail the target if the domain and application folders have under 95% coverage (see `tech/pytest.md`).

`test-security`, `test-integration`, `test-e2e` run the other test levels and need `make up`. `test-all` lists the four as prerequisites and runs them in order. `check: lint test` is "everything that needs no database", and it is what CI runs first.

### Quality and supply-chain targets

- `lint` runs four tools in sequence (`ruff check`, `ruff format --check`, `mypy`, `lint-imports`); the first failure stops it.
- `format` runs ruff with `--fix` and then `ruff format`.
- `audit` runs `pip-audit` on the lock file; `sbom` writes `sbom.cdx.json` with `cyclonedx-py` (see their notes).
- `prove` runs `scripts/prove_controls.py`.

### Containers and cleanup

`docker-build`, `docker-run` (`docker compose --profile app up -d --wait --build app`) and `down` (`docker compose --profile app down -v`; `-v` also deletes the data volume). `clean: down` depends on `down`, then removes the virtual environment and all tool caches with `rm -rf`.

### Every target

Every target in the `Makefile`, in file order, with what its recipe does. (`$(VENV)` is `.venv`, `$(PY)` is `.venv/bin/python`, `$(STAMP)` is `.venv/.installed`; a leading `@` hides the command from make's own echo.)

| Target | Prerequisites | What the recipe does |
| --- | --- | --- |
| `help` | none | Searches the Makefile for lines like `target: ... ## text`, rewrites `:` and `##` as a tab, sorts them and prints them. This is how every `##` comment becomes help text. |
| `$(STAMP)` | `requirements-dev.lock`, `pyproject.toml` | Creates the virtual environment, installs the locked dev packages, installs this project, then `touch`es the stamp file so make knows it is done (explained below). |
| `install` | `$(STAMP)` | Nothing of its own: asking for `install` forces the stamp rule. |
| `env` | none | `[ -f .env ] \|\| { cp .env.example .env; echo "created ..."; }`: create `.env` from the example only if it does not exist (`tech/bash.md`). |
| `up` | `env`, `$(STAMP)` | `docker compose up -d --wait postgres`, then asks the database whether the table `users` exists and runs the `db` target only if it does not. |
| `db` | none | Applies `sql/001_schema.sql` (passing the application role's password as `-v app_password=...`), `sql/002_seed.sql`, then every file in `sql/migrations/` in name order, printing `migrate <file>` for each. |
| `queries` | none | Runs `sql/003_queries.sql` through `psql` inside the database container. |
| `reset-db` | none | Runs `sql/reset.sql`, which empties every table. |
| `run` | `env`, `$(STAMP)` | Starts gunicorn in the foreground (`$(SERVE)`). Ctrl-C stops it gracefully. |
| `demo` | `env`, `$(STAMP)` | Runs `scripts/demo.sh`. |
| `health` | `$(STAMP)` | Runs the `notes-app-health` command: exit 0 when `/readyz` answers 200. |
| `lint` | `$(STAMP)` | Four commands in order: `ruff check .`, `ruff format --check .`, `mypy`, `lint-imports`. The first failure stops the recipe. |
| `format` | `$(STAMP)` | `ruff check --fix .` then `ruff format .`: apply fixes and formatting. |
| `test` | `$(STAMP)` | Unit tests with coverage, then `coverage report ... --fail-under=95` for the domain and application folders. |
| `test-security` | `$(STAMP)` | `pytest tests/security -v`. Needs the database. |
| `test-integration` | `$(STAMP)` | `pytest tests/integration -m integration`. |
| `test-e2e` | `$(STAMP)` | `pytest tests/e2e -m e2e`. |
| `test-all` | `test test-integration test-security test-e2e` | Runs the four test levels in that order. |
| `prove` | `$(STAMP)` | `python scripts/prove_controls.py`. |
| `audit` | `$(STAMP)` | `pip-audit --no-deps --disable-pip -r requirements-dev.lock`. |
| `sbom` | `$(STAMP)` | `cyclonedx-py requirements requirements.lock --of JSON -o sbom.cdx.json`, then prints `wrote sbom.cdx.json`. |
| `check` | `lint test` | Everything that needs no database. |
| `docker-build` | none | `docker build -t security-threat-model-and-harden:dev .` |
| `docker-run` | `env` | `docker compose --profile app up -d --wait --build app`. |
| `down` | none | `docker compose --profile app down -v`: stop the containers and delete their data. |
| `clean` | `down` | `rm -rf` the virtual environment, logs and every tool cache and the SBOM. |

The first line of the Makefile is only a comment (every line starting with `#`). `.PHONY:` lists the names that are jobs, not files, so a file named `test` could never make `make test` say "up to date".

#### How the stamp file works, step by step

1. You type `make test`. Make sees that `test` needs `$(STAMP)`, the file `.venv/.installed`.
2. If that file does not exist, or `requirements-dev.lock` or `pyproject.toml` is newer than it, make runs the stamp rule's recipe: `$(PYTHON) -m venv $(VENV)` creates a **virtual environment** (a private folder holding its own copy of the Python tools and its own installed packages, so this project's packages never collide with another project's); `pip install -q --require-hashes -r requirements-dev.lock` installs every locked package, refusing any file whose fingerprint is not in the lock (`tech/uv-and-lock-files.md`); `pip install -q --no-deps -e .` installs this project itself in "editable" mode (a link to `src/`, so edits take effect immediately); `touch $@` creates or updates the stamp file.
3. If the file exists and is newer than both prerequisites, nothing is reinstalled.

## Try it yourself

1. List every target with its description:
   ```bash
   make help
   ```
   Expect 22 lines such as `audit	check the locked dependencies for known vulnerabilities`.
2. See what a target would run without running it:
   ```bash
   make -n test
   ```
   Expect the two `python -m pytest` and `python -m coverage` lines printed, not executed.
3. Check the stamp-file idea:
   ```bash
   make install && make install
   ```
   Expect the second call to print `make: Nothing to be done for `install'.` (the quote characters differ between make versions).
4. Force a reinstall:
   ```bash
   touch pyproject.toml && make -n install
   ```
   Expect the `venv` and `pip install` lines to appear again.

## Mistakes people make

- Spaces instead of a tab at the start of a recipe line. The `.editorconfig` sets `indent_style = tab` for `Makefile`.
- Using `$VAR` where Make needs `$(VAR)`, or `$VAR` where the shell needs `$$VAR`.
- Forgetting `.PHONY`: if a file named `test` ever existed, `make test` would say "up to date". Every non-file target is listed.
- Each recipe line is a separate shell, so `cd dir` on one line does not affect the next. This Makefile never relies on that.
- Hiding failures with a leading `-` on a recipe line or with `|| true`. The Makefile never uses the leading `-` on a recipe; `|| true` appears only in `demo.sh`.

## Check yourself

1. What does `?=` mean?
   *Assign only if the variable has no value yet.*
2. Why does `.venv/.installed` exist?
   *Its timestamp tells make whether the lock file or `pyproject.toml` changed since the last install.*
3. What does `$$` do in a recipe?
   *It passes a literal `$` to the shell.*
4. Why is `-T` passed to `docker compose exec`?
   *No terminal is attached, so redirected input such as `< sql/001_schema.sql` works.*
5. What happens if one line of a recipe fails?
   *make stops and reports an error, unless the line begins with `-`.*

## Further reading

- GNU Make manual (version 3.81 on macOS; the manual for 4.x is a superset): https://www.gnu.org/software/make/manual/make.html
- Phony targets: https://www.gnu.org/software/make/manual/make.html#Phony-Targets
