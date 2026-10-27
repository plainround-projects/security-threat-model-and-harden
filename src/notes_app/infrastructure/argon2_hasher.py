"""Password hashing with argon2id: slow, memory-hard, random salt per hash, parameters inside the encoded value."""

from __future__ import annotations

from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class Argon2PasswordHasher:
    """The production ``PasswordHasher``."""

    def __init__(self, *, time_cost: int, memory_kib: int, parallelism: int) -> None:
        self._argon2 = Argon2(time_cost=time_cost, memory_cost=memory_kib, parallelism=parallelism)
        # A real hash of a throwaway value, so verifying a missing user costs what verifying a real one does.
        self._dummy_hash = self._argon2.hash("dummy-value-for-timing-equalization")

    def hash(self, password: str) -> str:
        """An encoded argon2id hash with a fresh random salt."""
        return self._argon2.hash(password)

    def verify(self, password: str, encoded: str) -> bool:
        """True only for the matching password; a malformed stored value verifies as False."""
        try:
            return self._argon2.verify(encoded, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, encoded: str) -> bool:
        """True when the stored hash was made with weaker parameters than the current ones."""
        try:
            return self._argon2.check_needs_rehash(encoded)
        except InvalidHashError:
            return True

    def spend_equal_effort(self, password: str) -> None:
        """Verify against a dummy hash and discard the result."""
        self.verify(password, self._dummy_hash)
