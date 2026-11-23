"""Cosine similarity of a query vector against chunk vectors (numpy)."""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from vendorguard.models.evidence import Chunk
from vendorguard.utils.jsonio import FLOAT_DECIMALS


class VectorIndex:
    """Chunk vectors, L2-normalised once, kept in chunk-ID order."""

    def __init__(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("one vector per chunk is required")
        if any(len(v) == 0 for v in vectors) or len({len(v) for v in vectors}) > 1:
            raise ValueError("vectors must be non-empty and share one dimension")
        order = sorted(range(len(chunks)), key=lambda i: chunks[i].chunk_id)
        self._ids = [chunks[i].chunk_id for i in order]
        if len(set(self._ids)) != len(self._ids):
            raise ValueError("chunk IDs must be unique")
        matrix = np.array([vectors[i] for i in order], dtype=np.float64).reshape(len(order), -1)
        self._matrix = _normalise(matrix)

    def scores(self, query: Sequence[float]) -> dict[str, float]:
        """Cosine similarity per chunk ID (0.0 for a zero vector), rounded to 6 decimals."""
        vector = np.array(query, dtype=np.float64)
        if self._matrix.shape[1] != vector.shape[0]:
            raise ValueError("the query vector has a different dimension than the chunk vectors")
        similarity = self._matrix @ _normalise(vector.reshape(1, -1))[0]
        return {
            cid: round(float(s), FLOAT_DECIMALS) + 0.0
            for cid, s in zip(self._ids, similarity, strict=True)
        }


def _normalise(rows: NDArray[np.float64]) -> NDArray[np.float64]:
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    return np.divide(rows, norms, out=np.zeros_like(rows), where=norms > 0)


__all__ = ["VectorIndex"]
