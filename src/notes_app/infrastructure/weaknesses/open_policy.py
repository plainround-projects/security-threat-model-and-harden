"""WEAKNESS (UNSAFE_SKIP_OWNERSHIP_CHECK): an access policy that trusts any id."""

from __future__ import annotations

from collections.abc import Collection

from notes_app.domain.access import Access


class AllowEverythingPolicy:
    """What the per-request authorization check replaces: if you know the id, you may do anything with it."""

    def access(self, *, owner_id: int, shared_with: Collection[int], user_id: int) -> Access:
        """Full access for everyone."""
        return Access.WRITE
