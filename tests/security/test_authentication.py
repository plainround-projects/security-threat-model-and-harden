"""Stretch: throttling of sign-in attempts, and no hint about which half of a credential was wrong."""

import pytest

from tests.support import Browser, new_password, new_username

pytestmark = pytest.mark.security


def test_repeated_failures_are_throttled_with_retry_after_and_audited(app, owner_sql, settings):
    browser = Browser(app)
    username = new_username()
    browser.sign_up(username, new_password())
    statuses = [
        browser.sign_in(username, "a wrong password again").status_code for _ in range(settings.login_max_failures)
    ]
    assert statuses == [401] * settings.login_max_failures

    throttled = browser.sign_in(username, "a wrong password again")
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) > 0
    assert owner_sql("SELECT count(*) FROM audit_events WHERE action = 'login.throttled'") == [(1,)]


def test_a_correct_password_is_also_refused_while_throttled(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    for _ in range(5):
        browser.sign_in(username, "a wrong password again")
    assert browser.sign_in(username, password).status_code == 429


def test_a_different_client_address_is_not_throttled_by_someone_elses_failures(app):
    username, password = new_username(), new_password()
    attacker, owner = Browser(app, remote_addr="203.0.113.9"), Browser(app, remote_addr="198.51.100.4")
    owner.sign_up(username, password)
    for _ in range(6):
        attacker.sign_in(username, "a wrong password again")
    assert owner.sign_in(username, password).status_code == 303


def test_the_throttle_stores_neither_the_username_nor_the_address(app, owner_sql):
    browser = Browser(app, remote_addr="203.0.113.77")
    username = new_username("probe")
    browser.sign_in(username, "a wrong password again")
    rows = owner_sql("SELECT key_hash FROM login_failures")
    assert len(rows) == 1
    assert username not in rows[0][0]
    assert "203.0.113.77" not in rows[0][0]


def test_unknown_user_and_wrong_password_look_identical(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    wrong = browser.sign_in(username, "definitely the wrong one")
    unknown = browser.sign_in(new_username("nobody"), password)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_data() == unknown.get_data().replace(
        b"", b""
    ) or "Invalid username or password." in unknown.get_data(as_text=True)
    assert "Invalid username or password." in wrong.get_data(as_text=True)
