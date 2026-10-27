"""Step 4: authorization is checked in the service for every note, on every request."""

import pytest

from tests.support import Browser

pytestmark = pytest.mark.security


@pytest.fixture
def two_users(app):
    user_a, user_b = Browser(app), Browser(app)
    user_a.register("usera")
    user_b.register("userb")
    return user_a, user_b, user_b.create_note("B's private note", "only for B")


def test_user_a_cannot_read_update_or_delete_user_b_note(two_users, owner_sql):
    client_a, _, user_b_note_id = two_users
    assert client_a.api("GET", f"/notes/{user_b_note_id}", csrf=None).status_code == 404
    assert client_a.api("PATCH", f"/notes/{user_b_note_id}", json={"content": "hacked"}).status_code == 404
    assert client_a.api("DELETE", f"/notes/{user_b_note_id}").status_code == 404
    assert owner_sql("SELECT content FROM notes WHERE id = %s", (user_b_note_id,)) == [("only for B",)]


def test_changing_the_id_in_the_url_reaches_no_note_of_another_user(two_users):
    client_a, _, user_b_note_id = two_users
    own_id = client_a.create_note("A's own note", "mine")
    reachable = [
        note_id
        for note_id in range(1, user_b_note_id + 5)
        if client_a.api("GET", f"/notes/{note_id}", csrf=None).status_code == 200
    ]
    assert reachable == [own_id]


def test_a_foreign_note_and_a_missing_note_are_indistinguishable(two_users):
    client_a, _, user_b_note_id = two_users
    foreign = client_a.api("GET", f"/notes/{user_b_note_id}", csrf=None)
    missing = client_a.api("GET", "/notes/999999", csrf=None)
    assert (foreign.status_code, foreign.get_json()) == (missing.status_code, missing.get_json())


def test_the_owner_in_the_request_body_is_ignored(two_users, owner_sql):
    client_a, _, _ = two_users
    owner_b = owner_sql("SELECT id FROM users ORDER BY id DESC LIMIT 1")[0][0]
    note_id = client_a.api("POST", "/notes", json={"title": "x", "content": "y", "owner_id": owner_b}).get_json()["id"]
    owner_a = owner_sql("SELECT owner_id FROM notes WHERE id = %s", (note_id,))[0][0]
    assert owner_a != owner_b


def test_every_notes_route_refuses_a_request_with_no_session(app):
    anonymous = Browser(app)
    token = anonymous.csrf_token()
    headers = {"Accept": "application/json", "X-CSRF-Token": token}
    for method, path in (
        ("GET", "/notes"),
        ("POST", "/notes"),
        ("GET", "/notes/1"),
        ("PATCH", "/notes/1"),
        ("DELETE", "/notes/1"),
        ("POST", "/notes/1/shares"),
    ):
        assert anonymous.request(method, path, headers=headers, json={}).status_code == 401, (method, path)


def test_a_user_the_note_is_shared_with_can_read_but_not_change_or_share_it(app, owner_sql):
    owner, reader = Browser(app), Browser(app)
    owner.register("owner")
    reader_name, _ = reader.register("reader")
    note_id = owner.create_note("Shared", "for the reader")
    assert owner.api("POST", f"/notes/{note_id}/shares", json={"username": reader_name}).status_code == 204

    assert reader.api("GET", f"/notes/{note_id}", csrf=None).get_json()["content"] == "for the reader"
    assert reader.api("PATCH", f"/notes/{note_id}", json={"content": "x"}).status_code == 403
    assert reader.api("DELETE", f"/notes/{note_id}").status_code == 403
    assert reader.api("POST", f"/notes/{note_id}/shares", json={"username": reader_name}).status_code == 403
    assert owner_sql("SELECT content FROM notes WHERE id = %s", (note_id,)) == [("for the reader",)]


def test_revoking_access_takes_effect_on_the_next_request(app, owner_sql):
    owner, reader = Browser(app), Browser(app)
    owner.register("owner")
    reader_name, _ = reader.register("reader")
    note_id = owner.create_note("Shared", "x")
    owner.api("POST", f"/notes/{note_id}/shares", json={"username": reader_name})
    assert reader.api("GET", f"/notes/{note_id}", csrf=None).status_code == 200
    owner_sql("DELETE FROM note_shares WHERE note_id = %s", (note_id,))
    assert reader.api("GET", f"/notes/{note_id}", csrf=None).status_code == 404  # looked up fresh every time
