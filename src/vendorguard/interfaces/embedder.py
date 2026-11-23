"""The embedding provider interface (docs/PLAN.md section 6)."""

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """Turns text into vectors. Implementations apply their own task prefixes."""

    model: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """The vector of a search query."""
        ...


__all__ = ["Embedder"]
