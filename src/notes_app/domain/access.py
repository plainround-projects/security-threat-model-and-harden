"""The authorization rule for notes, as a pure function so it can be tested without a database."""

from __future__ import annotations

from collections.abc import Collection
from enum import IntEnum


class Access(IntEnum):
    """What a user may do with one note. Ordered: each level includes the one below."""

    NONE = 0
    READ = 1
    WRITE = 2


def access_to_note(*, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
    """The owner may read and write; a user the note is shared with may read; everyone else gets nothing."""
    if user_id == owner_id:
        return Access.WRITE
    if user_id in shared_with:
        return Access.READ
    return Access.NONE
