"""The only clock in VendorGuard: no other module may read the current time directly."""

import time
from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime (patch this in tests to freeze time)."""
    return datetime.now(UTC)


def monotonic_s() -> float:
    """Seconds from a monotonic clock, for measuring durations (patch this in tests)."""
    return time.monotonic()


__all__ = ["monotonic_s", "utcnow"]
