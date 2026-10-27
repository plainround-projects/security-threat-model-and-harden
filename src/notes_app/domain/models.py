"""Immutable value objects of the notes app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class User:
    """A registered user. ``password_hash`` is an encoded argon2id hash, never a password."""

    id: int
    username: str
    password_hash: str = ""


@dataclass(frozen=True, slots=True)
class Note:
    """A note and its owner."""

    id: int
    owner_id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


class NoteRole(StrEnum):
    """How the requesting user relates to a note they can see."""

    OWNER = "owner"
    READER = "reader"


@dataclass(frozen=True, slots=True)
class VisibleNote:
    """A note together with the requester's role, as listed on the notes page."""

    note: Note
    role: NoteRole
    owner_username: str


@dataclass(frozen=True, slots=True)
class Session:
    """A server-side session. ``user_id`` is ``None`` until sign-in (an anonymous session carries the CSRF token
    of the sign-in form)."""

    token_hash: str
    user_id: int | None
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class AuditAction(StrEnum):
    """Security events worth an audit row."""

    SIGNUP = "signup"
    LOGIN_SUCCESS = "login.success"
    LOGIN_FAILURE = "login.failure"
    LOGIN_THROTTLED = "login.throttled"
    LOGOUT = "logout"
    NOTE_ACCESS_DENIED = "note.access_denied"
    NOTE_SHARED = "note.shared"
    NOTE_DELETED = "note.deleted"
    CSRF_REJECTED = "csrf.rejected"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One security-relevant event. ``detail`` holds ids and reasons only, never credentials or free text."""

    action: AuditAction
    outcome: str
    user_id: int | None
    ip: str
    detail: tuple[tuple[str, str], ...] = ()
