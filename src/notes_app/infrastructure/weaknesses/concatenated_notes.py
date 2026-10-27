"""WEAKNESS (UNSAFE_SQL_CONCATENATION): a note insert that splices its values into the statement text."""

from __future__ import annotations

from notes_app.domain.models import Note
from notes_app.infrastructure.postgres.notes import PostgresNoteRepository, to_note


class ConcatenatedNoteRepository(PostgresNoteRepository):
    """What the parameterized-query control replaces. A quote character in a title or in the content now changes
    the statement's structure, so a note containing one is a syntax error instead of text."""

    def add(self, owner_id: int, title: str, content: str) -> Note:
        """Insert by building the statement as a string."""
        statement = (
            "INSERT INTO notes (owner_id, title, content) VALUES ("  # noqa: S608 - deliberate weakness, APP_ENV=test only
            + str(owner_id)
            + ", '"
            + title
            + "', '"
            + content
            + "') RETURNING id, owner_id, title, content, created_at, updated_at"
        )
        with self._database.connection() as connection:
            row = connection.execute(statement).fetchone()
        assert row is not None  # noqa: S101
        return to_note(row)
