"""Step 5: session cookie flags, security headers and CSRF."""

import re

import pytest

from notes_app.interfaces.http.security import SESSION_COOKIE
from tests.support import Browser, new_password, new_username

pytestmark = pytest.mark.security
REQUIRED_HEADERS = {
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=",
}


def _session_cookie_header(response):
    cookies = [value for value in response.headers.getlist("Set-Cookie") if value.startswith(SESSION_COOKIE)]
    assert len(cookies) == 1
    return cookies[0]


def test_session_cookie_flags(app, owner_sql):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    cookie = _session_cookie_header(browser.sign_in(username, password))
    attributes = {part.strip().split("=")[0] for part in cookie.split(";")[1:]}
    assert {"HttpOnly", "Secure", "SameSite", "Path"} <= attributes
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie
    assert "Domain" not in cookie  # with the __Host- prefix, the browser enforces this too

    value = cookie.split("=", 1)[1].split(";", 1)[0]
    assert len(value) >= 40  # 256 bits of randomness
    assert re.fullmatch(r"[\w-]+\.[\w-]+\.[\w-]+", value) is None  # opaque: not a JWT carrying claims
    assert owner_sql("SELECT count(*) FROM sessions WHERE token_hash = %s", (value,)) == [
        (0,)
    ]  # only its hash is stored


def test_security_headers_on_every_response(app):
    browser = Browser(app)
    browser.register()
    responses = [
        browser.get("/login"),
        browser.get("/notes"),
        browser.get("/no-such-page"),
        browser.api("GET", "/notes/999999", csrf=None),
        browser.get("/healthz"),
        browser.get("/static/style.css"),
    ]
    for response in responses:
        for header, expected in REQUIRED_HEADERS.items():
            assert expected in response.headers.get(header, ""), (header, response.status_code)


def test_state_changing_request_without_csrf_token_is_refused(app, owner_sql):
    browser = Browser(app)
    browser.register()
    note_id = browser.create_note("Keep me", "x")

    assert browser.api("POST", "/notes", json={"title": "Forged", "content": "x"}, csrf=None).status_code == 403
    assert (
        browser.api("POST", "/notes", json={"title": "Forged", "content": "x"}, csrf="wrong-token").status_code == 403
    )
    assert browser.api("DELETE", f"/notes/{note_id}", csrf=None).status_code == 403
    assert browser.api("PATCH", f"/notes/{note_id}", json={"content": "forged"}, csrf=None).status_code == 403
    assert browser.post("/logout").status_code == 403
    assert owner_sql("SELECT title, content FROM notes") == [
        ("Keep me", "x")
    ]  # nothing was created, changed or deleted

    assert (
        browser.api("POST", "/notes", json={"title": "Real", "content": "x"}).status_code == 201
    )  # with the token it works


def test_another_sessions_csrf_token_does_not_work(app):
    victim, attacker = Browser(app), Browser(app)
    victim.register()
    attacker.register()
    assert (
        victim.api("POST", "/notes", json={"title": "x", "content": "y"}, csrf=attacker.csrf_token()).status_code == 403
    )


def test_the_session_id_changes_at_sign_in(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    before = browser.session_cookie()
    assert before is not None
    browser.sign_in(username, password)
    after = browser.session_cookie()
    assert after is not None
    assert after != before
    planted = Browser(app)
    planted.client.set_cookie(SESSION_COOKIE, before, domain="localhost")
    assert planted.get("/notes", headers={"Accept": "application/json"}).status_code == 401


def test_sign_out_ends_the_session_on_the_server(app, owner_sql):
    browser = Browser(app)
    browser.register()
    stolen = browser.session_cookie()
    assert browser.post("/logout", data={"csrf_token": browser.csrf_token()}).status_code == 303
    thief = Browser(app)
    thief.client.set_cookie(SESSION_COOKIE, stolen or "", domain="localhost")
    assert thief.get("/notes", headers={"Accept": "application/json"}).status_code == 401
    assert owner_sql("SELECT count(*) FROM sessions WHERE user_id IS NOT NULL") == [(0,)]


def test_a_session_past_its_expiry_is_refused(app, owner_sql):
    browser = Browser(app)
    browser.register()
    owner_sql("UPDATE sessions SET expires_at = now() - interval '1 second' WHERE user_id IS NOT NULL")
    assert browser.get("/notes", headers={"Accept": "application/json"}).status_code == 401


def test_an_idle_session_is_refused(app, owner_sql):
    browser = Browser(app)
    browser.register()
    owner_sql("UPDATE sessions SET last_seen_at = now() - interval '2 hours' WHERE user_id IS NOT NULL")
    assert browser.get("/notes", headers={"Accept": "application/json"}).status_code == 401


def test_an_unknown_or_malformed_cookie_value_is_refused(app):
    for value in ("never-issued", "a" * 3000, "../../etc/passwd", "' OR '1'='1"):
        browser = Browser(app)
        browser.client.set_cookie(SESSION_COOKIE, value, domain="localhost")
        assert browser.get("/notes", headers={"Accept": "application/json"}).status_code == 401
