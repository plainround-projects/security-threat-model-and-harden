"""In-memory stand-ins for the ports: the domain, application and HTTP layer are tested without a database."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from notes_app.domain.errors import UsernameTakenError
from notes_app.domain.models import AuditEvent, Note, NoteRole, Session, User, VisibleNote

START = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime = START) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


class CountingTokens:
    """Predictable tokens: token-1, token-2, ..."""

    def __init__(self) -> None:
        self._count = 0

    def new_token(self) -> str:
        self._count += 1
        return f"token-{self._count}"


class ReversibleHasher:
    """Not a real hash: lets service tests run instantly and check what was stored."""

    def __init__(self) -> None:
        self.dummy_calls = 0
        self.rehash_wanted = False

    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password: str, encoded: str) -> bool:
        return encoded == f"hashed:{password}"

    def needs_rehash(self, encoded: str) -> bool:
        return self.rehash_wanted

    def spend_equal_effort(self, password: str) -> None:
        self.dummy_calls += 1


class InMemoryUsers:
    def __init__(self) -> None:
        self.rows: dict[int, User] = {}

    def add(self, username: str, password_hash: str) -> User:
        if any(user.username == username for user in self.rows.values()):
            raise UsernameTakenError(username)
        user = User(id=len(self.rows) + 1, username=username, password_hash=password_hash)
        self.rows[user.id] = user
        return user

    def by_username(self, username: str) -> User | None:
        return next((user for user in self.rows.values() if user.username == username), None)

    def by_id(self, user_id: int) -> User | None:
        return self.rows.get(user_id)

    def update_password_hash(self, user_id: int, password_hash: str) -> None:
        self.rows[user_id] = replace(self.rows[user_id], password_hash=password_hash)


class InMemoryNotes:
    def __init__(self, users: InMemoryUsers, clock: FakeClock) -> None:
        self._users = users
        self._clock = clock
        self.notes: dict[int, Note] = {}
        self.shares: dict[int, set[int]] = {}

    def add(self, owner_id: int, title: str, content: str) -> Note:
        now = self._clock.now()
        note = Note(len(self.notes) + 1, owner_id, title, content, now, now)
        self.notes[note.id] = note
        return note

    def get(self, note_id: int) -> Note | None:
        return self.notes.get(note_id)

    def shared_with(self, note_id: int) -> frozenset[int]:
        return frozenset(self.shares.get(note_id, set()))

    def update(self, note_id: int, title: str, content: str) -> Note:
        note = replace(self.notes[note_id], title=title, content=content, updated_at=self._clock.now())
        self.notes[note_id] = note
        return note

    def delete(self, note_id: int) -> None:
        self.notes.pop(note_id, None)
        self.shares.pop(note_id, None)

    def share(self, note_id: int, user_id: int) -> None:
        self.shares.setdefault(note_id, set()).add(user_id)

    def list_visible(self, user_id: int) -> list[VisibleNote]:
        visible = []
        for note in self.notes.values():
            owner = self._users.rows[note.owner_id]
            if note.owner_id == user_id:
                visible.append(VisibleNote(note, NoteRole.OWNER, owner.username))
            elif user_id in self.shares.get(note.id, set()):
                visible.append(VisibleNote(note, NoteRole.READER, owner.username))
        return visible


class InMemorySessions:
    def __init__(self) -> None:
        self.rows: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        self.rows[session.token_hash] = session

    def get(self, token_hash: str) -> Session | None:
        return self.rows.get(token_hash)

    def touch(self, token_hash: str, seen_at: datetime) -> None:
        self.rows[token_hash] = replace(self.rows[token_hash], last_seen_at=seen_at)

    def delete(self, token_hash: str) -> None:
        self.rows.pop(token_hash, None)

    def purge_expired(self, now: datetime) -> int:
        expired = [key for key, session in self.rows.items() if session.expires_at <= now]
        for key in expired:
            del self.rows[key]
        return len(expired)


class ListAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)

    def actions(self) -> list[str]:
        return [event.action.value for event in self.events]


class RecordingThrottle:
    """Throttle double: records calls and can be told to refuse."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.resets: list[str] = []
        self.refuse_with: int | None = None

    def check(self, key: str, now: datetime) -> None:
        from notes_app.domain.errors import LoginThrottledError

        if self.refuse_with is not None:
            raise LoginThrottledError(self.refuse_with)

    def record_failure(self, key: str, now: datetime) -> None:
        self.failures.append(key)

    def reset(self, key: str) -> None:
        self.resets.append(key)


class InMemoryThrottle:
    """The same rule as the PostgreSQL throttle, kept in a dict, for tests that need real counting."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self._max = max_failures
        self._window = timedelta(seconds=window_seconds)
        self._failures: dict[str, list[datetime]] = {}

    def check(self, key: str, now: datetime) -> None:
        from notes_app.domain.errors import LoginThrottledError
        from notes_app.domain.throttle import retry_after_seconds

        wait = retry_after_seconds(self._failures.get(key, []), now=now, max_failures=self._max, window=self._window)
        if wait is not None:
            raise LoginThrottledError(wait)

    def record_failure(self, key: str, now: datetime) -> None:
        self._failures.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
