"""Notes and shares in PostgreSQL."""

from __future__ import annotations

from datetime import datetime

from notes_app.domain.models import Note, NoteRole, VisibleNote
from notes_app.infrastructure.postgres.database import Database

INSERT_NOTE = (
    "INSERT INTO notes (owner_id, title, content) VALUES (%s, %s, %s) "
    "RETURNING id, owner_id, title, content, created_at, updated_at"
)
SELECT_NOTE = "SELECT id, owner_id, title, content, created_at, updated_at FROM notes WHERE id = %s"
UPDATE_NOTE = (
    "UPDATE notes SET title = %s, content = %s, updated_at = now() WHERE id = %s "
    "RETURNING id, owner_id, title, content, created_at, updated_at"
)
DELETE_NOTE = "DELETE FROM notes WHERE id = %s"
SELECT_SHARES = "SELECT user_id FROM note_shares WHERE note_id = %s"
INSERT_SHARE = "INSERT INTO note_shares (note_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING"
LIST_VISIBLE = """
SELECT n.id, n.owner_id, n.title, n.content, n.created_at, n.updated_at, u.username,
       CASE WHEN n.owner_id = %(user_id)s THEN 'owner' ELSE 'reader' END AS role
FROM notes n
JOIN users u ON u.id = n.owner_id
WHERE n.owner_id = %(user_id)s
   OR EXISTS (SELECT 1 FROM note_shares s WHERE s.note_id = n.id AND s.user_id = %(user_id)s)
ORDER BY n.updated_at DESC, n.id DESC
"""


def to_note(row: tuple[object, ...]) -> Note:
    """Map the first six columns of a notes row."""
    return Note(
        id=int(str(row[0])),
        owner_id=int(str(row[1])),
        title=str(row[2]),
        content=str(row[3]),
        created_at=_timestamp(row[4]),
        updated_at=_timestamp(row[5]),
    )


def _timestamp(value: object) -> datetime:
    assert isinstance(value, datetime)  # noqa: S101 - timestamptz columns always come back as datetime
    return value


class PostgresNoteRepository:
    """The ``NoteRepository`` port over PostgreSQL. All values are bound parameters."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, owner_id: int, title: str, content: str) -> Note:
        """Insert a note with a parameterized statement."""
        with self._database.connection() as connection:
            row = connection.execute(INSERT_NOTE, (owner_id, title, content)).fetchone()
        assert row is not None  # noqa: S101 - RETURNING always yields the inserted row
        return to_note(row)

    def get(self, note_id: int) -> Note | None:
        """Fetch one note by id."""
        with self._database.connection() as connection:
            row = connection.execute(SELECT_NOTE, (note_id,)).fetchone()
        return None if row is None else to_note(row)

    def shared_with(self, note_id: int) -> frozenset[int]:
        """The ids of the users a note is shared with."""
        with self._database.connection() as connection:
            rows = connection.execute(SELECT_SHARES, (note_id,)).fetchall()
        return frozenset(int(str(row[0])) for row in rows)

    def update(self, note_id: int, title: str, content: str) -> Note:
        """Replace a note's title and content."""
        with self._database.connection() as connection:
            row = connection.execute(UPDATE_NOTE, (title, content, note_id)).fetchone()
        assert row is not None  # noqa: S101 - the service checked the note exists
        return to_note(row)

    def delete(self, note_id: int) -> None:
        """Delete a note; its shares go with it (ON DELETE CASCADE)."""
        with self._database.connection() as connection:
            connection.execute(DELETE_NOTE, (note_id,))

    def share(self, note_id: int, user_id: int) -> None:
        """Share a note with a user; sharing twice is a no-op."""
        with self._database.connection() as connection:
            connection.execute(INSERT_SHARE, (note_id, user_id))

    def list_visible(self, user_id: int) -> list[VisibleNote]:
        """Notes the user owns or has been given, newest first."""
        with self._database.connection() as connection:
            rows = connection.execute(LIST_VISIBLE, {"user_id": user_id}).fetchall()
        return [VisibleNote(note=to_note(row), role=NoteRole(str(row[7])), owner_username=str(row[6])) for row in rows]
