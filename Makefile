# make up | run | demo | test | test-security | prove | lint | audit | sbom | down      (make help lists everything)
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
POSTGRES_USER ?= notes_owner
POSTGRES_DB ?= notes
PSQL := docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 -q
SERVE := $(VENV)/bin/gunicorn -c python:notes_app.interfaces.gunicorn_conf "notes_app.interfaces.wsgi:build_app()"

-include .env
export

.PHONY: help install env up db seed migrate queries reset-db run demo health lint format test test-security \
        test-integration test-e2e test-all prove audit sbom check docker-build docker-run down clean

help: ## list the targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort

$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file

env:
	@[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }

# Start PostgreSQL and, on a fresh container, run the DDL, the seed and the migrations (see the sql/ folder).
up: env $(STAMP) ## start PostgreSQL and create the schema, seed and audit table
	docker compose up -d --wait postgres
	@if [ "$$($(PSQL) -tAc "SELECT to_regclass('public.users') IS NOT NULL")" = "t" ]; then \
	  echo "schema already present"; else $(MAKE) --no-print-directory db; fi

db: ## run sql/001_schema.sql, 002_seed.sql and sql/migrations/*.sql in order (fresh database only)
	$(PSQL) -v app_password="$(NOTES_DB_PASSWORD)" < sql/001_schema.sql
	$(PSQL) < sql/002_seed.sql
	@for file in sql/migrations/*.sql; do echo "migrate $$file"; $(PSQL) < $$file; done

queries: ## run sql/003_queries.sql: visible notes, shares, sessions, audit summary
	docker compose exec -T postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 < sql/003_queries.sql

reset-db: ## empty every table (sql/reset.sql)
	$(PSQL) < sql/reset.sql

# Foreground server: gunicorn on APP_HOST:APP_PORT, SIGTERM or Ctrl-C shuts it down gracefully.
run: env $(STAMP) ## start the app on http://127.0.0.1:8047 (needs make up)
	$(SERVE)

demo: env $(STAMP) ## run the lesson's scenario against a server started for the run (needs make up)
	scripts/demo.sh

health: $(STAMP) ## exit 0 when the running server answers /readyz
	$(VENV)/bin/notes-app-health

lint: $(STAMP) ## ruff check (with security rules), ruff format check, mypy, import-linter
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports

format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

# Unit tests need no database. The domain and application must stay at 95% coverage or more.
test: $(STAMP) ## unit tests with coverage (no database needed)
	$(PY) -m pytest tests/unit --cov=notes_app --cov-report=term
	$(PY) -m coverage report --include='src/notes_app/domain/*,src/notes_app/application/*' --fail-under=95

test-security: $(STAMP) ## one test per control of the threat model (needs make up)
	$(PY) -m pytest tests/security -v

test-integration: $(STAMP) ## the PostgreSQL adapters (needs make up)
	$(PY) -m pytest tests/integration -m integration

test-e2e: $(STAMP) ## the lesson's scenario over real HTTP against a started server (needs make up)
	$(PY) -m pytest tests/e2e -m e2e

test-all: test test-integration test-security test-e2e ## every test level (needs make up)

# The lesson's "does each test fail without its control?": run the security suite once per deliberate weakness.
prove: $(STAMP) ## run the security suite with each control removed in turn and show the tests fail (needs make up)
	$(PY) scripts/prove_controls.py

audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock

sbom: $(STAMP) ## write sbom.cdx.json (CycloneDX) for the locked runtime dependencies
	$(VENV)/bin/cyclonedx-py requirements requirements.lock --of JSON -o sbom.cdx.json
	@echo "wrote sbom.cdx.json"

check: lint test ## everything that needs no database

docker-build: ## build the container image
	docker build -t security-threat-model-and-harden:dev .

docker-run: env ## run the image against the compose database and wait until it is healthy (needs make up)
	docker compose --profile app up -d --wait --build app

down: ## stop the containers and delete their data
	docker compose --profile app down -v

clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .coverage sbom.cdx.json
