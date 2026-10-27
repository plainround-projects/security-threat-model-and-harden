"""Fixtures. APP_ENV is forced to ``test`` before any settings are read, the only environment where the deliberate
weaknesses (UNSAFE_* variables, used by ``make prove``) are accepted."""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from flask import Flask

from notes_app.infrastructure.logging import JsonFormatter
from notes_app.infrastructure.settings import Settings
from notes_app.interfaces.composition import Container, build_container
from notes_app.interfaces.http.app import create_app
from tests.support import Browser

os.environ["APP_ENV"] = "test"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings from the environment (``make`` exports .env), with fast argon2 parameters for speed."""
    env = dict(os.environ)
    env.setdefault("NOTES_DB_PASSWORD", "local-only-app-password")
    env["ARGON2_TIME_COST"] = "1"
    env["ARGON2_MEMORY_KIB"] = "1024"
    return Settings.from_environment(env)


def _owner_connection() -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=os.environ.get("NOTES_DB_HOST", "localhost"),
        port=int(os.environ.get("NOTES_DB_PORT", "5471")),
        dbname=os.environ.get("POSTGRES_DB", "notes"),
        user=os.environ.get("POSTGRES_USER", "notes_owner"),
        password=os.environ.get("POSTGRES_PASSWORD", "local-only-owner-password"),
        autocommit=True,
    )


@pytest.fixture
def owner_sql() -> Iterator[Callable[..., list[tuple[Any, ...]]]]:
    """Run SQL as the owner role (the test's window into the database); returns the rows, if any."""
    connection = _owner_connection()

    def run(statement: str, params: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
        cursor = connection.execute(statement, params)
        return cursor.fetchall() if cursor.description else []

    yield run
    connection.close()


@pytest.fixture
def container(settings: Settings, owner_sql: Callable[..., Any]) -> Iterator[Container]:
    """The wired application against an emptied database."""
    owner_sql((ROOT / "sql" / "reset.sql").read_text())
    wired = build_container(settings)
    wired.database.open()
    yield wired
    wired.database.close()


@pytest.fixture
def app(container: Container) -> Flask:
    return create_app(container)


@pytest.fixture
def browser(app: Flask) -> Browser:
    return Browser(app)


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    """Everything the application logs, rendered as the production JSON formatter renders it."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield stream
    root.removeHandler(handler)
    root.setLevel(previous_level)
