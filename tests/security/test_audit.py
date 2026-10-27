"""Stretch: security events are logged and recorded in an append-only table."""

import json

import psycopg
import pytest

from tests.support import HOSTILE, Browser, new_password, new_username

pytestmark = pytest.mark.security


def _audit_lines(captured_logs):
    lines = [json.loads(line) for line in captured_logs.getvalue().splitlines() if line.startswith("{")]
    return [line for line in lines if line.get("message") == "audit"]


def test_a_denied_note_access_writes_a_log_line_and_an_audit_row(app, owner_sql, captured_logs):
    intruder, owner = Browser(app), Browser(app)
    intruder.register("intruder")
    owner.register("owner")
    note_id = owner.create_note("Private", HOSTILE)
    assert intruder.api("GET", f"/notes/{note_id}", csrf=None).status_code == 404

    denied = [line for line in _audit_lines(captured_logs) if line["action"] == "note.access_denied"]
    assert len(denied) == 1
    assert denied[0]["note_id"] == str(note_id)
    assert denied[0]["reason"] == "no_access"
    rows = owner_sql("SELECT action, outcome, detail FROM audit_events WHERE action = 'note.access_denied'")
    assert rows == [("note.access_denied", "refused", {"note_id": str(note_id), "reason": "no_access"})]
    assert "script" not in captured_logs.getvalue()  # note content never reaches the log


def test_sign_up_sign_in_failure_and_sign_out_are_audited(app, owner_sql):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    browser.sign_in(username, "wrong password here!!")
    browser.sign_in(username, password)
    browser.post("/logout", data={"csrf_token": browser.csrf_token()})
    actions = [row[0] for row in owner_sql("SELECT action FROM audit_events ORDER BY id")]
    assert actions == ["signup", "login.failure", "login.success", "logout"]


def test_a_forged_request_is_audited(app, owner_sql):
    browser = Browser(app)
    browser.register()
    browser.api("POST", "/notes", json={"title": "x", "content": "y"}, csrf="forged")
    rows = owner_sql("SELECT action, detail FROM audit_events WHERE action = 'csrf.rejected'")
    assert rows == [("csrf.rejected", {"method": "POST", "path": "/notes"})]


def test_audit_detail_holds_only_ids_and_reasons(app, owner_sql):
    browser = Browser(app)
    username, password = new_username(), new_password()
    browser.sign_up(username, password)
    browser.sign_in(username, password)
    browser.sign_in("' OR '1'='1", "another wrong password")
    dump = json.dumps(owner_sql("SELECT user_id, ip, detail::text FROM audit_events"), default=str)
    assert username not in dump
    assert password not in dump
    assert "OR '1'" not in dump


def test_the_application_role_cannot_change_or_delete_audit_rows(container, owner_sql):
    owner_sql("INSERT INTO audit_events (action, outcome, ip) VALUES ('signup', 'success', '127.0.0.1')")
    with container.database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (1,)
    for statement in (
        "UPDATE audit_events SET outcome = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), container.database.connection() as connection:
            connection.execute(statement)
    assert owner_sql("SELECT outcome FROM audit_events") == [("success",)]


def test_even_the_owner_role_cannot_rewrite_history_with_update_or_delete(owner_sql):
    owner_sql("INSERT INTO audit_events (action, outcome, ip) VALUES ('signup', 'success', '127.0.0.1')")
    for statement in ("UPDATE audit_events SET outcome = 'tampered'", "DELETE FROM audit_events"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            owner_sql(statement)
