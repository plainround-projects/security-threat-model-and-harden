"""The production access policy: the domain rule, nothing more."""

from __future__ import annotations

from collections.abc import Collection

from notes_app.domain.access import Access, access_to_note


class OwnerOrSharedPolicy:
    """Owner writes, a user the note is shared with reads, everyone else gets nothing."""

    def access(self, *, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
        """The level of access the user has to the note."""
        return access_to_note(owner_id=owner_id, shared_with=shared_with, user_id=user_id)
