"""The audit trail: a structured log line first, then an append-only row."""

from __future__ import annotations

import logging

import psycopg
from psycopg.types.json import Jsonb

from notes_app.domain.models import AuditEvent
from notes_app.infrastructure.postgres.database import Database

_INSERT = "INSERT INTO audit_events (action, outcome, user_id, ip, detail) VALUES (%s, %s, %s, %s, %s)"
_log = logging.getLogger("notes_app.audit")


class PostgresAuditLog:
    """Writes each event to the ``audit`` logger and to the ``audit_events`` table.

    The application's database role can insert and read that table but not update or delete it, so a normal user
    of the app (or a bug) cannot rewrite history. A database failure is logged loudly and does not fail the
    request: the log line above is the fallback record.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, event: AuditEvent) -> None:
        """Write one event."""
        detail = dict(event.detail)
        _log.info(
            "audit",
            extra={
                "action": event.action.value,
                "outcome": event.outcome,
                "user_id": event.user_id,
                "ip": event.ip,
                **detail,
            },
        )
        try:
            with self._database.connection() as connection:
                connection.execute(_INSERT, (event.action.value, event.outcome, event.user_id, event.ip, Jsonb(detail)))
        except psycopg.Error:
            _log.exception("audit row could not be written", extra={"action": event.action.value})
