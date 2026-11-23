"""The cache backend interface (docs/PLAN.md section 6)."""

from typing import Any, Protocol


class CacheBackend(Protocol):
    """A key-value store for model-call results (JSON-compatible dicts)."""

    def get(self, key: str) -> dict[str, Any] | None:
        """The stored value, or ``None`` on a miss."""
        ...

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        """Store ``value`` under ``key``; ``purpose`` names the kind of call ("embedding", ...)."""
        ...


__all__ = ["CacheBackend"]
