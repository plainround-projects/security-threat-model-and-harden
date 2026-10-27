"""Server-side sessions with an opaque cookie value, rotation at sign-in and idle and absolute expiry."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import timedelta

from notes_app.application.ports import Clock, SessionRepository, TokenGenerator
from notes_app.domain.models import Session

TOUCH_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    """Lifetimes in seconds: how long an idle session lives, how long any session lives, and how long the
    anonymous session that carries the sign-in form's CSRF token lives."""

    idle_seconds: int
    absolute_seconds: int
    anonymous_seconds: int


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session and the raw cookie value, the only moment the raw value exists on the server."""

    raw_token: str
    session: Session
    max_age_seconds: int


def hash_token(raw_token: str) -> str:
    """The stored form of a cookie value: a database read never yields a usable session."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class SessionService:
    """Creates, resolves, rotates and ends sessions."""

    def __init__(
        self, sessions: SessionRepository, tokens: TokenGenerator, clock: Clock, policy: SessionPolicy
    ) -> None:
        self._sessions = sessions
        self._tokens = tokens
        self._clock = clock
        self._policy = policy

    def start_anonymous(self) -> IssuedSession:
        """A session before sign-in, so the sign-in and sign-up forms carry a CSRF token."""
        return self._issue(user_id=None, lifetime_seconds=self._policy.anonymous_seconds)

    def sign_in(self, previous_raw_token: str | None, user_id: int) -> IssuedSession:
        """Replace any earlier session with a new one for the user (defeats session fixation)."""
        if previous_raw_token:
            self._sessions.delete(hash_token(previous_raw_token))
        self._sessions.purge_expired(self._clock.now())
        return self._issue(user_id=user_id, lifetime_seconds=self._policy.absolute_seconds)

    def resolve(self, raw_token: str | None) -> Session | None:
        """The live session for a cookie value, or ``None`` when unknown, idle too long or past its expiry."""
        if not raw_token:
            return None
        token_hash = hash_token(raw_token)
        session = self._sessions.get(token_hash)
        if session is None:
            return None
        now = self._clock.now()
        idle_limit = session.last_seen_at + timedelta(seconds=self._policy.idle_seconds)
        if now >= session.expires_at or (session.user_id is not None and now >= idle_limit):
            self._sessions.delete(token_hash)
            return None
        if now - session.last_seen_at >= TOUCH_INTERVAL:
            self._sessions.touch(token_hash, now)
        return session

    def sign_out(self, raw_token: str | None) -> None:
        """Delete the session on the server; the cookie value stops meaning anything."""
        if raw_token:
            self._sessions.delete(hash_token(raw_token))

    @staticmethod
    def csrf_valid(session: Session, supplied: str | None) -> bool:
        """Constant-time comparison of the supplied token with the session's."""
        return supplied is not None and hmac.compare_digest(session.csrf_token.encode(), supplied.encode())

    def _issue(self, *, user_id: int | None, lifetime_seconds: int) -> IssuedSession:
        now = self._clock.now()
        raw_token = self._tokens.new_token()
        session = Session(
            token_hash=hash_token(raw_token),
            user_id=user_id,
            csrf_token=self._tokens.new_token(),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=lifetime_seconds),
        )
        self._sessions.add(session)
        return IssuedSession(raw_token, session, lifetime_seconds)
