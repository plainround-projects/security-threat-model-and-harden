"""The HTTP layer over in-memory fakes: routing, content negotiation, error mapping and cookie handling."""

from __future__ import annotations

import pytest
from flask import Flask

from notes_app.application.accounts import AccountService
from notes_app.application.notes import NoteService
from notes_app.application.policy import OwnerOrSharedPolicy
from notes_app.application.sessions import SessionPolicy, SessionService
from notes_app.infrastructure.settings import Settings
from notes_app.interfaces.composition import Container
from notes_app.interfaces.http.app import create_app
from notes_app.interfaces.http.security import SESSION_COOKIE
from tests.fakes import (
    CountingTokens,
    FakeClock,
    InMemoryNotes,
    InMemorySessions,
    InMemoryThrottle,
    InMemoryUsers,
    ListAudit,
    ReversibleHasher,
)
from tests.support import HOSTILE, Browser, new_password, new_username


class FakeDatabase:
    def __init__(self) -> None:
        self.healthy = True

    def ping(self) -> bool:
        return self.healthy

    def close(self) -> None:
        pass


@pytest.fixture
def parts():
    clock, users, audit = FakeClock(), InMemoryUsers(), ListAudit()
    settings = Settings.from_environment({"NOTES_DB_PASSWORD": "x", "APP_ENV": "test"})
    database = FakeDatabase()
    container = Container(
        settings=settings,
        database=database,  # type: ignore[arg-type]
        audit=audit,
        accounts=AccountService(
            users, ReversibleHasher(), InMemoryThrottle(max_failures=3, window_seconds=600), audit, clock
        ),
        sessions=SessionService(
            InMemorySessions(),
            CountingTokens(),
            clock,
            SessionPolicy(idle_seconds=1800, absolute_seconds=28800, anonymous_seconds=900),
        ),
        notes=NoteService(InMemoryNotes(users, clock), users, OwnerOrSharedPolicy(), audit),
    )
    return create_app(container), database, audit


@pytest.fixture
def app(parts) -> Flask:
    flask_app: Flask = parts[0]
    return flask_app


def test_health_endpoints(parts):
    app, database, _ = parts
    browser = Browser(app)
    assert browser.get("/healthz").get_json() == {"status": "ok"}
    assert browser.get("/readyz").status_code == 200
    database.healthy = False
    response = browser.get("/readyz")
    assert response.status_code == 503
    assert "Strict-Transport-Security" in response.headers


def test_sign_up_sign_in_and_the_notes_page(app):
    browser = Browser(app)
    username, _ = browser.register()
    page = browser.get("/notes")
    assert page.status_code == 200
    assert f"Signed in as {username}" in page.get_data(as_text=True)
    assert browser.get("/", follow_redirects=False).headers["Location"] == "/notes"


def test_an_anonymous_visitor_is_sent_to_sign_in_by_page_and_refused_by_api(app):
    browser = Browser(app)
    page = browser.get("/notes")
    assert (page.status_code, page.headers["Location"]) == (303, "/login")
    api = browser.get("/notes", headers={"Accept": "application/json"})
    assert api.status_code == 401
    assert api.get_json()["error"] == "unauthenticated"
    assert browser.get("/", follow_redirects=False).headers["Location"] == "/login"


def test_sign_up_reports_a_taken_username_and_a_weak_password_without_leaking_more(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    assert browser.sign_up(username, password).status_code == 303
    taken = browser.sign_up(username, password)
    assert taken.status_code == 400
    assert "not available" in taken.get_data(as_text=True)
    short = browser.sign_up(new_username(), "short")
    assert short.status_code == 400
    assert "12 to 128" in short.get_data(as_text=True)
    assert browser.get("/signup").status_code == 200


def test_wrong_password_and_unknown_user_give_the_same_response(app):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    wrong = browser.sign_in(username, "not the password at all")
    unknown = browser.sign_in(new_username(), password)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_data() == unknown.get_data() or "Invalid username or password." in unknown.get_data(as_text=True)


def test_the_fourth_failed_sign_in_is_throttled_with_retry_after(app):
    browser = Browser(app)
    username = new_username()
    browser.sign_up(username, new_password())
    statuses = [browser.sign_in(username, "wrong password number").status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
    throttled = browser.sign_in(username, "wrong password number")
    assert int(throttled.headers["Retry-After"]) > 0


def test_sign_out_clears_the_cookie_and_the_server_side_session(app, parts):
    browser = Browser(app)
    browser.register()
    old_cookie = browser.session_cookie()
    response = browser.post("/logout", data={"csrf_token": browser.csrf_token()})
    assert response.status_code == 303
    assert f"{SESSION_COOKIE}=;" in response.headers["Set-Cookie"]
    stale = Browser(app)
    stale.client.set_cookie(SESSION_COOKIE, old_cookie or "", domain="localhost")
    assert stale.get("/notes").status_code == 303


def test_a_post_without_a_session_or_token_is_refused_and_audited(app, parts):
    *_, audit = parts
    response = Browser(app).post("/login", data={"username": "a", "password": "b"})
    assert response.status_code == 403
    assert audit.actions() == ["csrf.rejected"]


def test_notes_through_the_json_api_and_the_pages(app):
    browser = Browser(app)
    browser.register()
    note_id = browser.create_note("Plan", "details")
    assert browser.api("GET", f"/notes/{note_id}", csrf=None).get_json()["content"] == "details"
    patched = browser.api("PATCH", f"/notes/{note_id}", json={"content": "changed"})
    assert patched.get_json()["content"] == "changed"
    listing = browser.get("/notes", headers={"Accept": "application/json"}).get_json()
    assert listing["notes"] == [{"id": note_id, "title": "Plan", "role": "owner"}]
    assert "Plan" in browser.get(f"/notes/{note_id}").get_data(as_text=True)
    assert browser.api("DELETE", f"/notes/{note_id}").status_code == 204
    assert browser.api("GET", f"/notes/{note_id}", csrf=None).status_code == 404


def test_the_form_flow_creates_a_note_and_redirects_to_it(app):
    browser = Browser(app)
    browser.register()
    response = browser.post(
        "/notes", data={"title": "From a form", "content": HOSTILE, "csrf_token": browser.csrf_token()}
    )
    assert response.status_code == 303
    page = browser.get(response.headers["Location"]).get_data(as_text=True)
    assert "&lt;script&gt;" in page
    assert "<script>" not in page
    invalid = browser.post("/notes", data={"title": "", "content": "x", "csrf_token": browser.csrf_token()})
    assert invalid.status_code == 400
    assert "1 to 120" in invalid.get_data(as_text=True)
    assert browser.api("POST", "/notes", json={"title": "", "content": "x"}).status_code == 400
    assert browser.api("POST", "/notes", json=["not", "an", "object"]).status_code == 400


def test_sharing_gives_a_second_user_read_only_access(app):
    owner, reader = Browser(app), Browser(app)
    owner.register()
    reader_name, _ = reader.register()
    note_id = owner.create_note("Shared", "hello")
    assert reader.api("GET", f"/notes/{note_id}", csrf=None).status_code == 404
    page_share = owner.post(
        f"/notes/{note_id}/shares", data={"username": reader_name, "csrf_token": owner.csrf_token()}
    )
    assert page_share.status_code == 303
    assert reader.api("GET", f"/notes/{note_id}", csrf=None).get_json()["content"] == "hello"
    assert reader.api("PATCH", f"/notes/{note_id}", json={"content": "x"}).status_code == 403
    bad = owner.post(f"/notes/{note_id}/shares", data={"username": "nobody_here", "csrf_token": owner.csrf_token()})
    assert bad.status_code == 400
    assert owner.api("POST", f"/notes/{note_id}/shares", json={"username": "nobody_here"}).status_code == 400
    assert owner.api("POST", f"/notes/{note_id}/shares", json={"username": reader_name}).status_code == 204


def test_unknown_routes_and_methods_use_the_same_error_shape(app):
    browser = Browser(app)
    assert browser.get("/nope").status_code == 404
    missing = browser.get("/nope", headers={"Accept": "application/json"})
    assert missing.status_code == 404
    assert missing.get_json()["error"] == "not_found"
    assert browser.get("/logout").status_code == 405


def test_an_unexpected_error_returns_no_internal_detail(parts):
    app, *_ = parts

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    response = Browser(app).get("/boom", headers={"Accept": "application/json"})
    assert response.status_code == 500
    assert "secret internal detail" not in response.get_data(as_text=True)
    assert response.get_json()["error"] == "internal_error"


def test_an_oversized_body_is_refused(app):
    browser = Browser(app)
    browser.register()
    response = browser.api("POST", "/notes", json={"title": "x", "content": "y" * 70_000})
    assert response.status_code == 413
