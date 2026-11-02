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

### Line by line: `Makefile`

Read the file as a list of **rules**: a line `target: prerequisites` followed by indented **recipe** lines (shell commands). Each recipe line starts with a tab character and runs in its own `/bin/sh`. The `##` text after a target is a comment that `make help` prints.

```make
# make up | run | demo | test | test-security | prove | lint | audit | sbom | down      (make help lists everything)
```

A comment listing the main targets.

```make
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
```

`PYTHON ?= ...` sets the variable only if it is not already set. `$(shell ...)` runs a command and uses its output; `command -v` prints the path of a program if it exists, and `||` tries the next one if not. So Python 3.13 is used if present, else 3.12, else any `python3`.

```make
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
```

`:=` assigns once, at this line. `VENV` is the folder of the **virtual environment** (a private folder with its own Python and its own installed packages). `PY` is the Python inside it. `STAMP` is an empty marker file that records that the install is done.

```make
POSTGRES_USER ?= notes_owner
POSTGRES_DB ?= notes
PSQL := docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 -q
```

`POSTGRES_USER` and `POSTGRES_DB` default to `notes_owner` and `notes`. `PSQL` is a command prefix: run `psql` inside the `postgres` container through `docker compose exec -T` (`-T` turns off the pseudo-terminal, needed when input is piped in) as the owner, with `-v ON_ERROR_STOP=1` (stop and exit non-zero at the first SQL error) and `-q` (quiet).

```make
SERVE := $(VENV)/bin/gunicorn -c python:notes_app.interfaces.gunicorn_conf "notes_app.interfaces.wsgi:build_app()"
```

`SERVE` is the gunicorn command line, used by the `run` target.

```make
-include .env
export
```

`-include .env` reads `.env` as more make variables if it exists (the `-` means no error if it is missing). A bare `export` then passes every make variable to the recipes as environment variables.

```make
.PHONY: help install env up db seed migrate queries reset-db run demo health lint format test test-security \
        test-integration test-e2e test-all prove audit sbom check docker-build docker-run down clean
```

`.PHONY` lists targets that are names, not files; without it a file called `test` would make `make test` do nothing.

```make
help: ## list the targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort
```

`help` runs `grep` to pick the lines that look like `name: ... ## text` from all makefiles (`-h` hides file names, `-E` enables extended patterns), `sed` to turn `: ... ## ` into a tab, and `sort`. `@` hides the command itself.

```make
$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@
```

The stamp rule depends on the lock file and `pyproject.toml`; it reruns when either is newer. It creates the virtual environment, installs the development lock with `--require-hashes` (pip refuses any package whose hash is not listed), installs the project itself with `--no-deps -e .` (an **editable** install that uses the code in `src/` directly) and `touch $@` creates the stamp (`$@` is the target's name).

```make
install: $(STAMP) ## create .venv from the lock file
```

`install` depends on the stamp.

```make
env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
```

`env` copies `.env.example` to `.env` if `.env` does not exist.

```make
# Start PostgreSQL and, on a fresh container, run the DDL, the seed and the migrations (see the sql/ folder).
up: env $(STAMP) ## start PostgreSQL and create the schema, seed and audit table
	docker compose up -d --wait postgres
	@if [ "$$($(PSQL) -tAc "SELECT to_regclass('public.users') IS NOT NULL")" = "t" ]; then \
	  echo "schema already present"; else $(MAKE) --no-print-directory db; fi
```

`up` needs `env` and the stamp. `docker compose up -d --wait postgres` starts the database in the background and waits for its health check. The `if` asks the database whether the table `users` exists (`to_regclass` is null if not; `-tAc` prints only the bare value, `t` for true). `$$` passes one `$` to the shell. If the schema is present it says so; otherwise `$(MAKE) --no-print-directory db` runs the `db` target.

```make
db: ## run sql/001_schema.sql, 002_seed.sql and sql/migrations/*.sql in order (fresh database only)
	$(PSQL) -v app_password="$(NOTES_DB_PASSWORD)" < sql/001_schema.sql
	$(PSQL) < sql/002_seed.sql
	@for file in sql/migrations/*.sql; do echo "migrate $$file"; $(PSQL) < $$file; done
```

`db` runs `001_schema.sql` with the app role's password from `NOTES_DB_PASSWORD`, then `002_seed.sql`, then a shell `for` loop over every file in `sql/migrations/` in name order, printing and running each.

```make
queries: ## run sql/003_queries.sql: visible notes, shares, sessions, audit summary
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 < sql/003_queries.sql
```

`queries` runs `003_queries.sql`.

```make
reset-db: ## empty every table (sql/reset.sql)
	$(PSQL) < sql/reset.sql
```

`reset-db` empties every table.

```make
# Foreground server: gunicorn on APP_HOST:APP_PORT, SIGTERM or Ctrl-C shuts it down gracefully.
run: env $(STAMP) ## start the app on http://127.0.0.1:8047 (needs make up)
	$(SERVE)
```

`run` starts the server in the foreground; SIGTERM or Ctrl-C shuts it down gracefully.

```make
demo: env $(STAMP) ## run the lesson's scenario against a server started for the run (needs make up)
	scripts/demo.sh
```

`demo` runs `scripts/demo.sh`.

```make
health: $(STAMP) ## exit 0 when the running server answers /readyz
	$(VENV)/bin/notes-app-health
```

`health` runs the health program.

```make
lint: $(STAMP) ## ruff check (with security rules), ruff format check, mypy, import-linter
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports
```

`lint` runs four checks, stopping at the first failure: `ruff check .`, `ruff format --check .`, `mypy` and `lint-imports`.

```make
format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .
```

`format` applies ruff's safe fixes and formatting.

```make
# Unit tests need no database. The domain and application must stay at 95% coverage or more.
test: $(STAMP) ## unit tests with coverage (no database needed)
	$(PY) -m pytest tests/unit --cov=notes_app --cov-report=term
	$(PY) -m coverage report --include='src/notes_app/domain/*,src/notes_app/application/*' --fail-under=95
```

`test` runs the unit tests with coverage, then `coverage report` for the domain and application folders with `--fail-under=95`: it fails if less than 95 percent of those lines ran.

```make
test-security: $(STAMP) ## one test per control of the threat model (needs make up)
	$(PY) -m pytest tests/security -v
```

`test-security` runs the security tests verbosely.

```make
test-integration: $(STAMP) ## the PostgreSQL adapters (needs make up)
	$(PY) -m pytest tests/integration -m integration
```

`test-integration` runs tests marked `integration`.

```make
test-e2e: $(STAMP) ## the lesson's scenario over real HTTP against a started server (needs make up)
	$(PY) -m pytest tests/e2e -m e2e
```

`test-e2e` runs tests marked `e2e`.

```make
test-all: test test-integration test-security test-e2e ## every test level (needs make up)
```

`test-all` is a list of other targets.

```make
# The lesson's "does each test fail without its control?": run the security suite once per deliberate weakness.
prove: $(STAMP) ## run the security suite with each control removed in turn and show the tests fail (needs make up)
	$(PY) scripts/prove_controls.py
```

`prove` runs the proof script that removes each control in turn.

```make
audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock
```

`audit` runs `pip-audit` on the lock (`--no-deps` stops it resolving more packages, `--disable-pip` stops it building a temporary environment).

```make
sbom: $(STAMP) ## write sbom.cdx.json (CycloneDX) for the locked runtime dependencies
	$(VENV)/bin/cyclonedx-py requirements requirements.lock --of JSON -o sbom.cdx.json
	@echo "wrote sbom.cdx.json"
```

`sbom` writes a CycloneDX bill of materials of the runtime lock file as JSON and prints a line.

```make
check: lint test ## everything that needs no database
```

`check` runs `lint` and `test`.

```make
docker-build: ## build the container image
	docker build -t security-threat-model-and-harden:dev .
```

`docker-build` builds the image and tags it.

```make
docker-run: env ## run the image against the compose database and wait until it is healthy (needs make up)
	docker compose --profile app up -d --wait --build app
```

`docker-run` starts the `app` service, which sits in the compose profile `app`, building it first and waiting for health.

```make
down: ## stop the containers and delete their data
	docker compose --profile app down -v
```

`down` stops the containers and deletes their data (`-v`).

```make
clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage sbom.cdx.json
```

`clean` removes the environment, logs, caches and the SBOM.

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
