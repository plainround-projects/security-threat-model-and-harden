"""gunicorn settings: ``gunicorn -c python:notes_app.interfaces.gunicorn_conf "notes_app.interfaces.wsgi:build_app()"``.

SIGTERM makes the master stop accepting connections, lets each worker finish its in-flight requests (up to
``graceful_timeout``), then each worker closes its database pool in ``worker_exit``.
"""

from __future__ import annotations

import os
from typing import Any

bind = f"{os.environ.get('APP_HOST', '127.0.0.1')}:{os.environ.get('APP_PORT', '8047')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 4
worker_class = "gthread"
timeout = 30
graceful_timeout = 20
keepalive = 5
control_socket_disable = True  # no admin socket in the home directory: one fewer local attack surface
limit_request_line = 4094
limit_request_fields = 50
accesslog = None  # the application writes one structured line per request
errorlog = "-"
logconfig_dict: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "notes_app.infrastructure.logging.JsonFormatter"}},
    "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stderr"}},
    "root": {"level": "INFO", "handlers": ["stderr"]},
    "loggers": {"gunicorn.error": {"handlers": ["stderr"], "level": "INFO", "propagate": False}},
}


def worker_exit(server: object, worker: object) -> None:
    """Called in the worker as it exits: close the database pool."""
    from notes_app.interfaces.wsgi import close_all

    close_all()
