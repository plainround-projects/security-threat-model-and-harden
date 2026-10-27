"""System clock and token source."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


class SystemClock:
    """The real time, in UTC."""

    def now(self) -> datetime:
        """The current UTC time."""
        return datetime.now(UTC)


class SecretsTokenGenerator:
    """Tokens from the operating system's CSPRNG: 32 bytes, 256 bits."""

    def new_token(self) -> str:
        """A URL-safe token."""
        return secrets.token_urlsafe(32)
