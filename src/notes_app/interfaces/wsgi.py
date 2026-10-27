"""WSGI entry point: ``gunicorn "notes_app.interfaces.wsgi:build_app()"``."""

from __future__ import annotations

import logging
import os

from flask import Flask

from notes_app.infrastructure.logging import configure_logging
from notes_app.infrastructure.settings import Settings
from notes_app.interfaces.composition import Container, build_container
from notes_app.interfaces.http.app import create_app

_containers: list[Container] = []


def build_app() -> Flask:
    """Read settings from the environment, open the database pool and return the application.

    Raises ``ConfigError`` (and so refuses to start) on a missing or invalid setting.
    """
    settings = Settings.from_environment(os.environ)
    configure_logging(settings.log_level)
    container = build_container(settings)
    container.database.open()
    _containers.append(container)
    logging.getLogger("notes_app").info(
        "started", extra={"app_env": settings.app_env, "weaknesses_enabled": list(settings.weaknesses.enabled())}
    )
    if settings.weaknesses.enabled():
        logging.getLogger("notes_app").warning("deliberate weaknesses are ON; this is a test run")
    return create_app(container)


def close_all() -> None:
    """Close the database pools of every application this process built (graceful shutdown)."""
    while _containers:
        _containers.pop().database.close()
    logging.getLogger("notes_app").info("database pool closed")
