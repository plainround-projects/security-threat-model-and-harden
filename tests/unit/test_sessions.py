from dataclasses import replace

import pytest

from notes_app.application.sessions import SessionPolicy, SessionService, hash_token
from tests.fakes import CountingTokens, FakeClock, InMemorySessions

POLICY = SessionPolicy(idle_seconds=1800, absolute_seconds=28800, anonymous_seconds=900)


@pytest.fixture
def parts():
    sessions, clock = InMemorySessions(), FakeClock()
    return sessions, clock, SessionService(sessions, CountingTokens(), clock, POLICY)


def test_only_the_hash_of_the_cookie_value_is_stored(parts):
    sessions, _, service = parts
    issued = service.start_anonymous()
    assert issued.raw_token not in sessions.rows
    assert hash_token(issued.raw_token) in sessions.rows
    assert issued.session.user_id is None


def test_an_anonymous_session_expires_quickly_and_a_signed_in_one_lasts_longer(parts):
    _, _, service = parts
    anonymous = service.start_anonymous()
    signed_in = service.sign_in(None, user_id=7)
    assert anonymous.max_age_seconds == 900
    assert signed_in.max_age_seconds == 28800


def test_signing_in_replaces_the_previous_session_and_its_csrf_token(parts):
    sessions, _, service = parts
    anonymous = service.start_anonymous()
    signed_in = service.sign_in(anonymous.raw_token, user_id=7)
    assert signed_in.raw_token != anonymous.raw_token
    assert service.resolve(anonymous.raw_token) is None  # the pre-login value no longer works
    assert signed_in.session.csrf_token != anonymous.session.csrf_token
    assert len(sessions.rows) == 1


def test_resolve_returns_the_session_until_it_has_been_idle_too_long(parts):
    _, clock, service = parts
    issued = service.sign_in(None, user_id=7)
    clock.advance(minutes=29)
    assert service.resolve(issued.raw_token) is not None
    clock.advance(minutes=31)
    assert service.resolve(issued.raw_token) is None


def test_activity_keeps_a_session_alive_past_the_idle_limit_but_not_the_absolute_limit(parts):
    _, clock, service = parts
    issued = service.sign_in(None, user_id=7)
    for _ in range(16):  # every 29 minutes, for 7 hours and 44 minutes
        clock.advance(minutes=29)
        assert service.resolve(issued.raw_token) is not None
    clock.advance(minutes=29)  # past 8 hours
    assert service.resolve(issued.raw_token) is None


def test_an_expired_session_is_deleted_when_it_is_found(parts):
    sessions, clock, service = parts
    issued = service.sign_in(None, user_id=7)
    clock.advance(hours=9)
    assert service.resolve(issued.raw_token) is None
    assert sessions.rows == {}


def test_unknown_or_missing_cookie_values_resolve_to_nothing(parts):
    *_, service = parts
    assert service.resolve(None) is None
    assert service.resolve("") is None
    assert service.resolve("never-issued") is None


def test_last_seen_is_written_at_most_once_a_minute(parts):
    sessions, clock, service = parts
    issued = service.sign_in(None, user_id=7)
    clock.advance(seconds=30)
    service.resolve(issued.raw_token)
    assert sessions.rows[hash_token(issued.raw_token)].last_seen_at != clock.now()
    clock.advance(seconds=31)
    service.resolve(issued.raw_token)
    assert sessions.rows[hash_token(issued.raw_token)].last_seen_at == clock.now()


def test_sign_out_removes_the_session(parts):
    _, _, service = parts
    issued = service.sign_in(None, user_id=7)
    service.sign_out(issued.raw_token)
    service.sign_out(None)
    assert service.resolve(issued.raw_token) is None


def test_sign_in_purges_sessions_past_their_expiry(parts):
    sessions, clock, service = parts
    stale = service.start_anonymous()
    clock.advance(hours=1)
    service.sign_in(None, user_id=7)
    assert hash_token(stale.raw_token) not in sessions.rows


def test_csrf_token_comparison(parts):
    _, _, service = parts
    session = service.start_anonymous().session
    assert service.csrf_valid(session, session.csrf_token)
    assert not service.csrf_valid(session, "wrong")
    assert not service.csrf_valid(session, None)
    assert not service.csrf_valid(replace(session, csrf_token="a"), "b")
