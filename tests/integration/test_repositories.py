"""The PostgreSQL adapters against the real database (make up)."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from notes_app.domain.errors import LoginThrottledError, UsernameTakenError
from notes_app.domain.models import AuditAction, AuditEvent, NoteRole, Session
from notes_app.infrastructure.postgres.audit import PostgresAuditLog
from notes_app.infrastructure.postgres.notes import PostgresNoteRepository
from notes_app.infrastructure.postgres.sessions import PostgresSessionRepository
from notes_app.infrastructure.postgres.throttle import PostgresLoginThrottle
from notes_app.infrastructure.postgres.users import PostgresUserRepository

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


@pytest.fixture
def users(container):
    return PostgresUserRepository(container.database)


@pytest.fixture
def notes(container):
    return PostgresNoteRepository(container.database)


def test_users_are_added_found_and_rehashed(users):
    alice = users.add("alice", "hash-1")
    assert users.by_username("alice") == alice
    assert users.by_id(alice.id) == alice
    assert users.by_username("nobody") is None
    assert users.by_id(999) is None
    users.update_password_hash(alice.id, "hash-2")
    assert users.by_id(alice.id).password_hash == "hash-2"


def test_the_unique_constraint_not_a_lookup_refuses_a_duplicate_username(users):
    users.add("alice", "hash")
    with pytest.raises(UsernameTakenError):
        users.add("alice", "another-hash")


def test_the_schema_rejects_a_username_outside_the_allow_list(container):
    with pytest.raises(psycopg.errors.CheckViolation), container.database.connection() as connection:
        connection.execute("INSERT INTO users (username, password_hash) VALUES ('Bad Name', 'x')")


def test_notes_are_created_read_updated_and_deleted_with_their_shares(users, notes):
    owner, reader = users.add("owner", "h"), users.add("reader", "h")
    note = notes.add(owner.id, "Title", "Content")
    assert notes.get(note.id) == note
    assert notes.get(999) is None
    notes.share(note.id, reader.id)
    notes.share(note.id, reader.id)  # idempotent
    assert notes.shared_with(note.id) == frozenset({reader.id})
    updated = notes.update(note.id, "New", "Changed")
    assert (updated.title, updated.content) == ("New", "Changed")
    assert updated.updated_at >= note.updated_at
    notes.delete(note.id)
    assert notes.get(note.id) is None
    assert notes.shared_with(note.id) == frozenset()


def test_the_visible_list_has_owned_and_shared_notes_with_roles_newest_first(users, notes):
    alice, bob, carol = users.add("alice", "h"), users.add("bob", "h"), users.add("carol", "h")
    first = notes.add(alice.id, "First", "x")
    second = notes.add(bob.id, "Second", "y")
    notes.add(carol.id, "Hidden", "z")
    notes.share(second.id, alice.id)
    visible = notes.list_visible(alice.id)
    assert [(item.note.id, item.role, item.owner_username) for item in visible] == [
        (second.id, NoteRole.READER, "bob"),
        (first.id, NoteRole.OWNER, "alice"),
    ]


def test_a_title_over_the_limit_is_refused_by_the_database_too(users, notes):
    owner = users.add("owner", "h")
    with pytest.raises(psycopg.errors.CheckViolation):
        notes.add(owner.id, "x" * 121, "content")


def test_sessions_round_trip_and_touch(container):
    sessions = PostgresSessionRepository(container.database)
    session = Session("hash-1", None, "csrf", NOW, NOW, NOW + timedelta(hours=1))
    sessions.add(session)
    assert sessions.get("hash-1") == session
    sessions.touch("hash-1", NOW + timedelta(minutes=5))
    touched = sessions.get("hash-1")
    assert touched is not None
    assert touched.last_seen_at == NOW + timedelta(minutes=5)
    sessions.delete("hash-1")
    assert sessions.get("hash-1") is None


def test_purging_removes_only_expired_sessions(container):
    sessions = PostgresSessionRepository(container.database)
    sessions.add(Session("old", None, "c", NOW, NOW, NOW - timedelta(seconds=1)))
    sessions.add(Session("live", None, "c", NOW, NOW, NOW + timedelta(hours=1)))
    assert sessions.purge_expired(NOW) == 1
    assert sessions.get("old") is None
    assert sessions.get("live") is not None


def test_the_throttle_counts_per_key_ages_out_and_resets(container):
    throttle = PostgresLoginThrottle(container.database, max_failures=2, window_seconds=600)
    throttle.record_failure("ip|alice", NOW)
    throttle.check("ip|alice", NOW)
    throttle.record_failure("ip|alice", NOW + timedelta(seconds=1))
    with pytest.raises(LoginThrottledError) as refused:
        throttle.check("ip|alice", NOW + timedelta(seconds=2))
    assert 595 <= refused.value.retry_after_seconds <= 600
    throttle.check("ip|bob", NOW + timedelta(seconds=2))  # another key is unaffected
    throttle.check("ip|alice", NOW + timedelta(seconds=602))  # the failures aged out
    throttle.reset("ip|alice")
    throttle.check("ip|alice", NOW + timedelta(seconds=2))


def test_recording_a_failure_prunes_rows_that_left_every_window(container, owner_sql):
    throttle = PostgresLoginThrottle(container.database, max_failures=5, window_seconds=600)
    throttle.record_failure("ip|alice", NOW)
    throttle.record_failure("ip|alice", NOW + timedelta(hours=1))
    assert owner_sql("SELECT count(*) FROM login_failures") == [(1,)]


def test_an_audit_event_is_stored_with_its_detail(container, owner_sql):
    PostgresAuditLog(container.database).record(
        AuditEvent(AuditAction.NOTE_SHARED, "success", None, "10.0.0.1", (("note_id", "7"),))
    )
    assert owner_sql("SELECT action, outcome, user_id, ip, detail FROM audit_events") == [
        ("note.shared", "success", None, "10.0.0.1", {"note_id": "7"})
    ]


def test_a_failing_audit_write_is_logged_and_does_not_fail_the_request(container, caplog, monkeypatch):
    def broken():
        raise psycopg.OperationalError("database went away")

    monkeypatch.setattr(container.database, "connection", broken)
    PostgresAuditLog(container.database).record(AuditEvent(AuditAction.LOGOUT, "success", 1, "10.0.0.1"))
    assert "audit row could not be written" in caplog.text
