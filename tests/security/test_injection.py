"""Step 3: parameterized queries and output encoding."""

import pytest

from tests.support import HOSTILE, Browser, new_password, new_username

pytestmark = pytest.mark.security


def test_hostile_content_is_stored_exactly_as_text(browser, owner_sql):
    browser.register()
    note_id = browser.create_note(title="It's a 'quoted' title", content=HOSTILE)
    stored = owner_sql("SELECT title, content FROM notes WHERE id = %s", (note_id,))
    assert stored == [("It's a 'quoted' title", HOSTILE)]  # stored exactly, no SQL side effect from the quote
    assert owner_sql("SELECT count(*) FROM notes") == [(1,)]
    assert owner_sql("SELECT count(*) FROM users") == [(1,)]  # the rest of the database is untouched


def test_hostile_content_is_rendered_as_inert_text(app, owner_sql):
    browser = Browser(app)
    username, _ = browser.register()
    owner_id = owner_sql("SELECT id FROM users WHERE username = %s", (username,))[0][0]
    # Inserted through the owner connection so this test isolates output encoding from query construction.
    note_id = owner_sql(
        "INSERT INTO notes (owner_id, title, content) VALUES (%s, %s, %s) RETURNING id",
        (owner_id, "<b>bold</b> title", HOSTILE),
    )[0][0]

    page = browser.get(f"/notes/{note_id}").get_data(as_text=True)
    assert "<script>" not in page  # the literal tag characters never appear unescaped
    assert "&lt;script&gt;" in page  # it was encoded, not stripped or executed
    listing = browser.get("/notes").get_data(as_text=True)
    assert "<b>bold</b>" not in listing
    assert "&lt;b&gt;bold&lt;/b&gt;" in listing
    json_page = browser.api("GET", f"/notes/{note_id}", csrf=None)
    assert json_page.content_type == "application/json"  # JSON is data, never rendered as markup


def test_sql_metacharacters_in_the_sign_in_form_are_just_a_failed_sign_in(app, owner_sql):
    browser = Browser(app)
    browser.sign_up(new_username(), new_password())
    for username in ("' OR '1'='1' --", "admin'; DROP TABLE users; --"):
        response = browser.sign_in(username, "' OR '1'='1")
        assert response.status_code == 401
    assert owner_sql("SELECT count(*) FROM users") == [(1,)]


def test_a_note_content_with_a_percent_and_a_backslash_round_trips(browser, owner_sql):
    browser.register()
    awkward = r"100% of C:\temp\new and %s and {0}"
    note_id = browser.create_note(content=awkward)
    assert owner_sql("SELECT content FROM notes WHERE id = %s", (note_id,)) == [(awkward,)]
