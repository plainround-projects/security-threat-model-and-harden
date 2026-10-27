"""Input validation at the boundary: allow-lists and length limits, no escaping (that is the output's job)."""

from __future__ import annotations

import re

from notes_app.domain.errors import InvalidInputError

USERNAME_PATTERN = re.compile(r"[a-z0-9_]{3,32}")
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
TITLE_MAX_LENGTH = 120
CONTENT_MAX_LENGTH = 10_000


def validate_username(raw: str) -> str:
    """Return the canonical (lower-case) username or raise ``InvalidInputError``."""
    username = raw.strip().lower()
    if USERNAME_PATTERN.fullmatch(username) is None:
        raise InvalidInputError("username", "use 3 to 32 letters, digits or underscores")
    return username


def validate_password(raw: str) -> str:
    """Length is the only rule that matters (NIST SP 800-63B); the upper bound stops hash-time abuse."""
    if not PASSWORD_MIN_LENGTH <= len(raw) <= PASSWORD_MAX_LENGTH:
        raise InvalidInputError("password", f"use {PASSWORD_MIN_LENGTH} to {PASSWORD_MAX_LENGTH} characters")
    return raw


def validate_note_title(raw: str) -> str:
    """A note title is one non-empty line of at most 120 characters."""
    title = raw.strip()
    if not title or len(title) > TITLE_MAX_LENGTH:
        raise InvalidInputError("title", f"use 1 to {TITLE_MAX_LENGTH} characters")
    if "\x00" in title or "\n" in title or "\r" in title:
        raise InvalidInputError("title", "use a single line")
    return title


def validate_note_content(raw: str) -> str:
    """Note content is free text up to 10,000 characters. Markup is allowed because output encoding handles it;
    a NUL byte is refused because PostgreSQL cannot store it."""
    if len(raw) > CONTENT_MAX_LENGTH:
        raise InvalidInputError("content", f"use at most {CONTENT_MAX_LENGTH} characters")
    if "\x00" in raw:
        raise InvalidInputError("content", "remove the NUL character")
    return raw
