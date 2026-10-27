"""Notes use cases. Every read, update, delete and share goes through one authorization check."""

from __future__ import annotations

from notes_app.application.ports import AccessPolicy, AuditLog, NoteRepository, UserRepository
from notes_app.domain.access import Access
from notes_app.domain.errors import InvalidInputError, NoteForbiddenError, NoteNotFoundError
from notes_app.domain.models import AuditAction, AuditEvent, Note, VisibleNote
from notes_app.domain.validation import validate_note_content, validate_note_title, validate_username


class NoteService:
    """The service layer of the threat model: the boundary where "does this user own or share this note?" is
    asked on every request, with the answer looked up fresh from the database."""

    def __init__(self, notes: NoteRepository, users: UserRepository, policy: AccessPolicy, audit: AuditLog) -> None:
        self._notes = notes
        self._users = users
        self._policy = policy
        self._audit = audit

    def create(self, user_id: int, title: str, content: str) -> Note:
        """Create a note owned by the user."""
        return self._notes.add(user_id, validate_note_title(title), validate_note_content(content))

    def get(self, user_id: int, note_id: int, ip: str) -> Note:
        """Read a note the user owns or has been given."""
        return self._authorize(user_id, note_id, Access.READ, ip)

    def update(self, user_id: int, note_id: int, title: str | None, content: str | None, ip: str) -> Note:
        """Change a note's title or content; only the owner may."""
        note = self._authorize(user_id, note_id, Access.WRITE, ip)
        new_title = validate_note_title(title) if title is not None else note.title
        new_content = validate_note_content(content) if content is not None else note.content
        return self._notes.update(note_id, new_title, new_content)

    def delete(self, user_id: int, note_id: int, ip: str) -> None:
        """Delete a note; only the owner may."""
        self._authorize(user_id, note_id, Access.WRITE, ip)
        self._notes.delete(note_id)
        self._audit.record(AuditEvent(AuditAction.NOTE_DELETED, "success", user_id, ip, (("note_id", str(note_id)),)))

    def share(self, user_id: int, note_id: int, username: str, ip: str) -> None:
        """Share a note with one other user by username; only the owner may."""
        self._authorize(user_id, note_id, Access.WRITE, ip)
        target = self._users.by_username(validate_username(username))
        if target is None or target.id == user_id:
            raise InvalidInputError("username", "choose another existing user")
        self._notes.share(note_id, target.id)
        detail = (("note_id", str(note_id)), ("shared_with", str(target.id)))
        self._audit.record(AuditEvent(AuditAction.NOTE_SHARED, "success", user_id, ip, detail))

    def list_visible(self, user_id: int) -> list[VisibleNote]:
        """The notes the user owns or has been given."""
        return self._notes.list_visible(user_id)

    def _authorize(self, user_id: int, note_id: int, needed: Access, ip: str) -> Note:
        note = self._notes.get(note_id)
        if note is None:
            raise NoteNotFoundError(f"note {note_id}")
        access = self._policy.access(
            owner_id=note.owner_id, shared_with=self._notes.shared_with(note_id), user_id=user_id
        )
        if access >= needed:
            return note
        reason = "no_access" if access is Access.NONE else "read_only"
        self._audit.record(
            AuditEvent(
                AuditAction.NOTE_ACCESS_DENIED, "refused", user_id, ip, (("note_id", str(note_id)), ("reason", reason))
            )
        )
        if access is Access.NONE:
            raise NoteNotFoundError(f"note {note_id}")
        raise NoteForbiddenError(f"note {note_id}")
