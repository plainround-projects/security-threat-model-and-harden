import pytest

from notes_app.application.notes import NoteService
from notes_app.application.policy import OwnerOrSharedPolicy
from notes_app.domain.errors import InvalidInputError, NoteForbiddenError, NoteNotFoundError
from notes_app.domain.models import NoteRole
from tests.fakes import FakeClock, InMemoryNotes, InMemoryUsers, ListAudit

ALICE, BOB, CAROL = 1, 2, 3


@pytest.fixture
def parts():
    users = InMemoryUsers()
    for name in ("alice", "bob", "carol"):
        users.add(name, "!")
    notes, audit = InMemoryNotes(users, FakeClock()), ListAudit()
    return notes, audit, NoteService(notes, users, OwnerOrSharedPolicy(), audit)


def test_owner_creates_reads_updates_and_deletes_a_note(parts):
    notes, audit, service = parts
    note = service.create(ALICE, " Plan ", "details")
    assert service.get(ALICE, note.id, "ip").title == "Plan"
    updated = service.update(ALICE, note.id, None, "new details", "ip")
    assert (updated.title, updated.content) == ("Plan", "new details")
    service.delete(ALICE, note.id, "ip")
    assert notes.get(note.id) is None
    assert audit.actions() == ["note.deleted"]


@pytest.mark.parametrize("action", ["get", "update", "delete", "share"])
def test_a_stranger_gets_not_found_for_every_action_and_the_attempt_is_audited(parts, action):
    _, audit, service = parts
    note = service.create(ALICE, "Private", "secret")
    calls = {
        "get": lambda: service.get(BOB, note.id, "ip"),
        "update": lambda: service.update(BOB, note.id, "x", "y", "ip"),
        "delete": lambda: service.delete(BOB, note.id, "ip"),
        "share": lambda: service.share(BOB, note.id, "carol", "ip"),
    }
    with pytest.raises(NoteNotFoundError):
        calls[action]()
    assert audit.actions() == ["note.access_denied"]
    assert dict(audit.events[0].detail) == {"note_id": str(note.id), "reason": "no_access"}


def test_a_missing_note_and_a_foreign_note_raise_the_same_error(parts):
    _, _, service = parts
    note = service.create(ALICE, "Private", "secret")
    with pytest.raises(NoteNotFoundError) as foreign:
        service.get(BOB, note.id, "ip")
    with pytest.raises(NoteNotFoundError) as missing:
        service.get(BOB, 999, "ip")
    assert type(foreign.value) is type(missing.value)


def test_a_reader_can_read_but_gets_forbidden_for_update_delete_and_share(parts):
    _, audit, service = parts
    note = service.create(ALICE, "Shared", "hello")
    service.share(ALICE, note.id, "bob", "ip")
    assert service.get(BOB, note.id, "ip").content == "hello"
    for call in (
        lambda: service.update(BOB, note.id, "x", None, "ip"),
        lambda: service.delete(BOB, note.id, "ip"),
        lambda: service.share(BOB, note.id, "carol", "ip"),
    ):
        with pytest.raises(NoteForbiddenError):
            call()
    assert audit.actions().count("note.access_denied") == 3
    assert dict(audit.events[-1].detail)["reason"] == "read_only"


def test_sharing_with_yourself_or_an_unknown_user_is_refused(parts):
    *_, service = parts
    note = service.create(ALICE, "Plan", "x")
    for username in ("alice", "nobody"):
        with pytest.raises(InvalidInputError):
            service.share(ALICE, note.id, username, "ip")


def test_listing_shows_owned_and_shared_notes_with_the_role(parts):
    *_, service = parts
    own = service.create(BOB, "Mine", "x")
    other = service.create(ALICE, "Theirs", "y")
    service.create(CAROL, "Hidden", "z")
    service.share(ALICE, other.id, "bob", "ip")
    visible = {item.note.id: item.role for item in service.list_visible(BOB)}
    assert visible == {own.id: NoteRole.OWNER, other.id: NoteRole.READER}


def test_update_validates_the_new_values(parts):
    *_, service = parts
    note = service.create(ALICE, "Plan", "x")
    with pytest.raises(InvalidInputError):
        service.update(ALICE, note.id, "", None, "ip")
    with pytest.raises(InvalidInputError):
        service.update(ALICE, note.id, None, "a\x00b", "ip")
