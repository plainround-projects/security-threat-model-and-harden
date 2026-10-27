"""Step 2: passwords are stored as salted slow hashes and never logged."""

import pytest

from tests.support import Browser, new_password, new_username

pytestmark = pytest.mark.security


def _hashes(owner_sql, *usernames):
    rows = owner_sql("SELECT username, password_hash FROM users WHERE username = ANY(%s)", (list(usernames),))
    return dict(rows)


def test_passwords_are_salted_and_not_logged(app, owner_sql, captured_logs):
    password = new_password()
    first, second = Browser(app), Browser(app)
    name_a, name_b = new_username("a"), new_username("b")
    assert first.sign_up(name_a, password).status_code == 303
    assert second.sign_up(name_b, password).status_code == 303
    assert first.sign_in(name_a, password).status_code == 303
    assert first.sign_in(name_a, "a different wrong password").status_code == 401

    stored = _hashes(owner_sql, name_a, name_b)
    assert stored[name_a] != stored[name_b]  # same password, different hash: salted
    assert stored[name_a].startswith("$argon2id$")  # a real algorithm identifier, not a raw digest
    assert password not in stored[name_a]
    assert password not in captured_logs.getvalue()  # never appears in any log line
    assert "a different wrong password" not in captured_logs.getvalue()


def test_the_login_response_and_pages_never_echo_the_password(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    response = browser.sign_in(username, "not the right password")
    assert "not the right password" not in response.get_data(as_text=True)
    assert response.status_code == 401
