"""Ports: what the use cases need from the outside world. Adapters live in ``infrastructure``."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Protocol

from notes_app.domain.access import Access
from notes_app.domain.models import AuditEvent, Note, Session, User, VisibleNote


class UserRepository(Protocol):
    """Storage of users."""

    def add(self, username: str, password_hash: str) -> User:
        """Insert a user; raise ``UsernameTakenError`` when the username exists."""

    def by_username(self, username: str) -> User | None:
        """Find a user by canonical username."""

    def by_id(self, user_id: int) -> User | None:
        """Find a user by id."""

    def update_password_hash(self, user_id: int, password_hash: str) -> None:
        """Replace the stored hash (after a parameter upgrade)."""


class NoteRepository(Protocol):
    """Storage of notes and their shares. Every method takes values; none builds SQL from them."""

    def add(self, owner_id: int, title: str, content: str) -> Note:
        """Insert a note."""

    def get(self, note_id: int) -> Note | None:
        """Fetch one note by id, whoever owns it. Authorization is the service's job."""

    def shared_with(self, note_id: int) -> frozenset[int]:
        """The ids of the users a note is shared with."""

    def update(self, note_id: int, title: str, content: str) -> Note:
        """Replace a note's title and content."""

    def delete(self, note_id: int) -> None:
        """Delete a note and its shares."""

    def share(self, note_id: int, user_id: int) -> None:
        """Share a note with a user (idempotent)."""

    def list_visible(self, user_id: int) -> list[VisibleNote]:
        """Every note the user owns or has been given, newest first."""


class SessionRepository(Protocol):
    """Storage of sessions, keyed by the hash of the cookie value."""

    def add(self, session: Session) -> None:
        """Insert a session."""

    def get(self, token_hash: str) -> Session | None:
        """Fetch a session by token hash."""

    def touch(self, token_hash: str, seen_at: datetime) -> None:
        """Record activity."""

    def delete(self, token_hash: str) -> None:
        """Remove a session (sign-out or rotation)."""

    def purge_expired(self, now: datetime) -> int:
        """Remove every session past its absolute expiry; return how many."""


class AuditLog(Protocol):
    """Append-only record of security events."""

    def record(self, event: AuditEvent) -> None:
        """Write one event."""


class PasswordHasher(Protocol):
    """Slow, salted password hashing."""

    def hash(self, password: str) -> str:
        """Hash with a fresh random salt."""

    def verify(self, password: str, encoded: str) -> bool:
        """Constant-effort check of a password against a stored hash."""

    def needs_rehash(self, encoded: str) -> bool:
        """True when the stored hash uses weaker parameters than the current ones."""

    def spend_equal_effort(self, password: str) -> None:
        """Do the work of a verification for a user that does not exist, so timing does not reveal them."""


class LoginThrottle(Protocol):
    """Limits failed sign-ins per client and username."""

    def check(self, key: str, now: datetime) -> None:
        """Raise ``LoginThrottledError`` when the key is over the limit."""

    def record_failure(self, key: str, now: datetime) -> None:
        """Count one failed sign-in."""

    def reset(self, key: str) -> None:
        """Forget the failures (after a successful sign-in)."""


class AccessPolicy(Protocol):
    """Decides what a user may do with a note."""

    def access(self, *, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
        """The level of access the user has."""


class Clock(Protocol):
    """Time, injected so tests are deterministic."""

    def now(self) -> datetime:
        """The current time, timezone-aware (UTC)."""


class TokenGenerator(Protocol):
    """Unguessable tokens for sessions and CSRF."""

    def new_token(self) -> str:
        """A URL-safe token with at least 256 bits of randomness."""
