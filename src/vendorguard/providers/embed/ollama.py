"""Embeddings from a local Ollama server (``POST /api/embed``), in batches, with task prefixes."""

import math
from collections.abc import Sequence
from typing import Any

import httpx

from vendorguard.config_models.providers import EmbeddingsSettings
from vendorguard.errors import EmbeddingError

MAX_ERROR_CHARS = 200


class OllamaEmbedder:
    """Calls Ollama's embedding endpoint; every failure becomes an ``EmbeddingError``."""

    def __init__(self, settings: EmbeddingsSettings, client: httpx.Client | None = None) -> None:
        self.model = settings.model
        self._settings = settings
        self._url = f"{settings.base_url.rstrip('/')}/api/embed"
        self._client = client or httpx.Client(timeout=settings.timeout_s)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``doc_prefix + text`` for each text, ``batch_size`` texts per request."""
        prefixed = [self._settings.doc_prefix + text for text in texts]
        size = self._settings.batch_size
        vectors: list[list[float]] = []
        for start in range(0, len(prefixed), size):
            vectors.extend(self._request(prefixed[start : start + size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed ``query_prefix + text``."""
        return self._request([self._settings.query_prefix + text])[0]

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()

    def _request(self, inputs: list[str]) -> list[list[float]]:
        try:
            response = self._client.post(self._url, json={"model": self.model, "input": inputs})
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama embedding request failed ({type(exc).__name__})") from exc
        if response.status_code != 200:
            raise EmbeddingError(
                f"Ollama returned HTTP {response.status_code}: {_detail(response)}"
            )
        try:
            vectors = _parse(response.json(), len(inputs))
        except ValueError as exc:
            raise EmbeddingError(f"unusable Ollama embedding response: {exc}") from exc
        return vectors


def _detail(response: httpx.Response) -> str:
    try:
        message = response.json().get("error", "")
    except (ValueError, AttributeError):
        message = response.text
    return str(message)[:MAX_ERROR_CHARS]


def _parse(data: Any, expected: int) -> list[list[float]]:
    vectors = data.get("embeddings") if isinstance(data, dict) else None
    if not isinstance(vectors, list) or len(vectors) != expected:
        raise ValueError(f"expected {expected} embeddings")
    out: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise ValueError("an embedding is not a non-empty list")
        if not all(isinstance(x, int | float) and not isinstance(x, bool) for x in vector):
            raise ValueError("an embedding holds non-numeric values")
        floats = [float(x) for x in vector]
        if not all(math.isfinite(x) for x in floats):
            raise ValueError("an embedding holds NaN or infinite values")
        out.append(floats)
    if len({len(v) for v in out}) > 1:
        raise ValueError("embeddings have different dimensions")
    return out


__all__ = ["OllamaEmbedder"]
