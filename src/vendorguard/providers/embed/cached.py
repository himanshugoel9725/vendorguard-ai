"""Cache wrapper for any embedder: each text is embedded once per (model, prefix, text)."""

from collections.abc import Sequence
from typing import Any

from vendorguard.errors import EmbeddingError
from vendorguard.interfaces.cache import CacheBackend
from vendorguard.interfaces.embedder import Embedder
from vendorguard.utils.hashing import hash_obj, sha256_text

PURPOSE = "embedding"


class CachedEmbedder:
    """Looks each text up in the cache and sends only the misses to the wrapped embedder.

    ``hits`` and ``misses`` count distinct lookups (a text repeated within one call counts once).
    The prefixes belong in the key so that changing them never serves stale vectors.
    """

    def __init__(
        self, inner: Embedder, cache: CacheBackend, doc_prefix: str, query_prefix: str
    ) -> None:
        self.model = inner.model
        self.hits = 0
        self.misses = 0
        self._inner = inner
        self._cache = cache
        self._doc_prefix = doc_prefix
        self._query_prefix = query_prefix

    def key(self, prefix: str, text: str) -> str:
        """Cache key: hash of the model, the prefix and the SHA-256 of the text (never the text)."""
        return hash_obj(
            {
                "kind": PURPOSE,
                "model": self.model,
                "prefix": prefix,
                "text_sha256": sha256_text(text),
            }
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectors in input order; cached ones are reused, the rest are computed in one call."""
        keys = [self.key(self._doc_prefix, text) for text in texts]
        found: dict[str, list[float]] = {}
        missing: dict[str, str] = {}
        for key, text in zip(keys, texts, strict=True):
            if key in found or key in missing:
                continue
            vector = self._lookup(key)
            if vector is None:
                missing[key] = text
            else:
                found[key] = vector
                self.hits += 1
        if missing:
            computed = self._inner.embed_documents(list(missing.values()))
            if len(computed) != len(missing):
                raise EmbeddingError("the embedder returned the wrong number of vectors")
            for key, vector in zip(missing, computed, strict=True):
                self._cache.put(key, {"embedding": vector}, purpose=PURPOSE)
                found[key] = vector
            self.misses += len(missing)
        return [found[key] for key in keys]

    def embed_query(self, text: str) -> list[float]:
        """The vector of a query, cached like a document."""
        key = self.key(self._query_prefix, text)
        vector = self._lookup(key)
        if vector is not None:
            self.hits += 1
            return vector
        vector = self._inner.embed_query(text)
        self._cache.put(key, {"embedding": vector}, purpose=PURPOSE)
        self.misses += 1
        return vector

    def _lookup(self, key: str) -> list[float] | None:
        entry: dict[str, Any] | None = self._cache.get(key)
        vector = entry.get("embedding") if entry else None
        return vector if isinstance(vector, list) else None  # a damaged entry counts as a miss


__all__ = ["CachedEmbedder"]
