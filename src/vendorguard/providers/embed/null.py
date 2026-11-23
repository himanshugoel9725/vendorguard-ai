"""The ``none`` embedder: no vectors, so retrieval is BM25 only and fully deterministic."""

from collections.abc import Sequence

NULL_MODEL = "none"


class NullEmbedder:
    """Empty vectors; retrieval skips the vector signal when ``embeddings.provider`` is none."""

    model = NULL_MODEL

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """An empty vector for each text."""
        return [[] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        """An empty vector."""
        return []


__all__ = ["NULL_MODEL", "NullEmbedder"]
