"""The sliding-window rule behind the sign-in throttle, as a pure function."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta


def retry_after_seconds(
    failures: Iterable[datetime], *, now: datetime, max_failures: int, window: timedelta
) -> int | None:
    """Seconds until another attempt is allowed, or ``None`` when the key is under its limit.

    ``failures`` are the timestamps of earlier failed sign-ins. Only those inside the window count; once
    ``max_failures`` of them are inside it, the next attempt waits until the oldest of those ages out.
    """
    live = sorted(moment for moment in failures if moment > now - window)
    if len(live) < max_failures:
        return None
    blocking = live[len(live) - max_failures]
    return max(int((blocking + window - now).total_seconds()) + 1, 1)
