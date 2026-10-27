"""WEAKNESS (UNSAFE_WEAK_PASSWORD_HASH): an unsalted fast digest instead of a password hash."""

from __future__ import annotations

import hashlib
import hmac


class UnsaltedSha256Hasher:
    """What the argon2 control replaces: fast, no salt, identical passwords give identical hashes."""

    def hash(self, password: str) -> str:
        """A bare SHA-256 digest."""
        return hashlib.sha256(password.encode()).hexdigest()

    def verify(self, password: str, encoded: str) -> bool:
        """Compare digests."""
        return hmac.compare_digest(self.hash(password), encoded)

    def needs_rehash(self, encoded: str) -> bool:
        """Never; there are no parameters."""
        return False

    def spend_equal_effort(self, password: str) -> None:
        """Nothing to equalize."""
