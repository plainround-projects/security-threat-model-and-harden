"""The composition root: the one place that knows which adapter implements which port."""

from __future__ import annotations

from dataclasses import dataclass

from notes_app.application.accounts import AccountService
from notes_app.application.notes import NoteService
from notes_app.application.policy import OwnerOrSharedPolicy
from notes_app.application.ports import AccessPolicy, AuditLog, PasswordHasher
from notes_app.application.sessions import SessionService
from notes_app.infrastructure.argon2_hasher import Argon2PasswordHasher
from notes_app.infrastructure.clock import SecretsTokenGenerator, SystemClock
from notes_app.infrastructure.postgres.audit import PostgresAuditLog
from notes_app.infrastructure.postgres.database import Database
from notes_app.infrastructure.postgres.notes import PostgresNoteRepository
from notes_app.infrastructure.postgres.sessions import PostgresSessionRepository
from notes_app.infrastructure.postgres.throttle import PostgresLoginThrottle
from notes_app.infrastructure.postgres.users import PostgresUserRepository
from notes_app.infrastructure.settings import Settings
from notes_app.infrastructure.weaknesses.concatenated_notes import ConcatenatedNoteRepository
from notes_app.infrastructure.weaknesses.open_policy import AllowEverythingPolicy
from notes_app.infrastructure.weaknesses.unsalted_sha256_hasher import UnsaltedSha256Hasher


@dataclass(frozen=True, slots=True)
class Container:
    """The wired application: settings, the database and the three services the HTTP layer calls."""

    settings: Settings
    database: Database
    audit: AuditLog
    accounts: AccountService
    sessions: SessionService
    notes: NoteService


def build_container(settings: Settings) -> Container:
    """Wire adapters into use cases. A deliberate weakness (APP_ENV=test only) swaps one adapter here."""
    weak = settings.weaknesses
    database = Database(settings.database)
    clock = SystemClock()
    audit = PostgresAuditLog(database)
    users = PostgresUserRepository(database)
    hasher: PasswordHasher = (
        UnsaltedSha256Hasher()
        if weak.weak_password_hash
        else Argon2PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_kib=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
        )
    )
    policy: AccessPolicy = AllowEverythingPolicy() if weak.skip_ownership_check else OwnerOrSharedPolicy()
    notes_repository = (
        ConcatenatedNoteRepository(database) if weak.sql_concatenation else PostgresNoteRepository(database)
    )
    throttle = PostgresLoginThrottle(
        database, max_failures=settings.login_max_failures, window_seconds=settings.login_window_seconds
    )
    return Container(
        settings=settings,
        database=database,
        audit=audit,
        accounts=AccountService(users, hasher, throttle, audit, clock),
        sessions=SessionService(PostgresSessionRepository(database), SecretsTokenGenerator(), clock, settings.session),
        notes=NoteService(notes_repository, users, policy, audit),
    )
