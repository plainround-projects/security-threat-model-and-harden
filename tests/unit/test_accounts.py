import pytest

from notes_app.application.accounts import AccountService
from notes_app.domain.errors import (
    AuthenticationFailedError,
    InvalidInputError,
    LoginThrottledError,
    UsernameTakenError,
)
from tests.fakes import FakeClock, InMemoryUsers, ListAudit, RecordingThrottle, ReversibleHasher

PASSWORD = "a long enough passphrase"


@pytest.fixture
def parts():
    users, hasher, throttle, audit = InMemoryUsers(), ReversibleHasher(), RecordingThrottle(), ListAudit()
    return users, hasher, throttle, audit, AccountService(users, hasher, throttle, audit, FakeClock())


def test_register_stores_a_hash_never_the_password(parts):
    users, hasher, _, audit, service = parts
    user = service.register("Alice", PASSWORD, "10.0.0.1")
    assert user.username == "alice"
    assert users.by_username("alice").password_hash == hasher.hash(PASSWORD)
    assert users.by_username("alice").password_hash != PASSWORD
    assert audit.actions() == ["signup"]


def test_register_refuses_a_taken_username(parts):
    *_, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    with pytest.raises(UsernameTakenError):
        service.register("ALICE", PASSWORD, "10.0.0.1")


def test_register_refuses_a_short_password(parts):
    *_, service = parts
    with pytest.raises(InvalidInputError):
        service.register("alice", "short", "10.0.0.1")


def test_authenticate_returns_the_user_and_resets_the_throttle(parts):
    _, _, throttle, audit, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    user = service.authenticate("alice", PASSWORD, "10.0.0.1")
    assert user.username == "alice"
    assert throttle.resets == ["10.0.0.1|alice"]
    assert audit.actions() == ["signup", "login.success"]


def test_wrong_password_and_unknown_user_fail_the_same_way(parts):
    _, hasher, throttle, audit, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    with pytest.raises(AuthenticationFailedError) as wrong_password:
        service.authenticate("alice", "wrong password here", "10.0.0.1")
    with pytest.raises(AuthenticationFailedError) as unknown_user:
        service.authenticate("nobody", PASSWORD, "10.0.0.1")
    assert str(wrong_password.value) == str(unknown_user.value)
    assert hasher.dummy_calls == 1  # the unknown user still cost one hash verification
    assert len(throttle.failures) == 2
    assert audit.actions()[-2:] == ["login.failure", "login.failure"]


def test_a_malformed_username_is_just_a_failed_login(parts):
    *_, service = parts
    with pytest.raises(AuthenticationFailedError):
        service.authenticate("x'; DROP TABLE users;--", PASSWORD, "10.0.0.1")


def test_a_throttled_client_is_refused_before_any_password_check(parts):
    _, hasher, throttle, audit, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    throttle.refuse_with = 42
    with pytest.raises(LoginThrottledError) as error:
        service.authenticate("alice", PASSWORD, "10.0.0.1")
    assert error.value.retry_after_seconds == 42
    assert hasher.dummy_calls == 0
    assert audit.actions()[-1] == "login.throttled"


def test_a_hash_with_old_parameters_is_upgraded_at_sign_in(parts):
    users, hasher, _, _, service = parts
    service.register("alice", PASSWORD, "10.0.0.1")
    hasher.rehash_wanted = True
    service.authenticate("alice", PASSWORD, "10.0.0.1")
    assert users.by_username("alice").password_hash == hasher.hash(PASSWORD)


def test_get_user_returns_the_registered_user(parts):
    *_, service = parts
    user = service.register("alice", PASSWORD, "10.0.0.1")
    assert service.get_user(user.id) == user
    assert service.get_user(999) is None
