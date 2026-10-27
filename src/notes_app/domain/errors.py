"""Named errors. Each one maps to exactly one HTTP outcome at the interface layer."""

from __future__ import annotations


class NotesError(Exception):
    """Base class of every error the application raises on purpose."""


class InvalidInputError(NotesError):
    """A value failed validation at a boundary."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


class UsernameTakenError(NotesError):
    """Sign-up asked for a username that already exists."""


class AuthenticationFailedError(NotesError):
    """Sign-in failed. The message never says whether the username or the password was wrong."""


class LoginThrottledError(NotesError):
    """Too many failed sign-ins for this client and username in the window."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"too many failed sign-ins, retry in {retry_after_seconds} seconds")
        self.retry_after_seconds = retry_after_seconds


class NoteNotFoundError(NotesError):
    """The note does not exist, or the caller may not know that it does.

    Both cases raise this one error so a response never confirms which ids exist.
    """


class NoteForbiddenError(NotesError):
    """The caller can see the note but lacks the right for this action (a reader trying to edit)."""


class CsrfRejectedError(NotesError):
    """A state-changing request arrived without the session's CSRF token."""
