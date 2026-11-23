"""The only clock in VendorGuard: no other module may read the current time directly."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime (patch this in tests to freeze time)."""
    return datetime.now(UTC)


__all__ = ["utcnow"]
