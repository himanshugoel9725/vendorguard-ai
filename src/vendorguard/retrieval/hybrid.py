"""Hybrid retrieval: BM25 and (optionally) embedding similarity, each min-max normalised."""

from collections.abc import Sequence

from vendorguard.config_models.core import RetrievalSettings
from vendorguard.interfaces.embedder import Embedder
from vendorguard.models.control import Control
from vendorguard.models.evidence import Chunk, ScoredChunk
from vendorguard.retrieval.bm25_index import Bm25Index
from vendorguard.retrieval.query_builder import build_query
from vendorguard.retrieval.tokenizer import Tokenizer
from vendorguard.retrieval.vector_index import VectorIndex
from vendorguard.utils.jsonio import FLOAT_DECIMALS


def min_max(scores: dict[str, float]) -> dict[str, float]:
    """Scale to [0, 1].

    When every score is equal there is nothing to rank: a positive value (all chunks match equally,
    or the only chunk matches) is a real signal and becomes 1.0, while zero or less becomes 0.0.
    """
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high == low:
        return dict.fromkeys(scores, 1.0 if high > 0 else 0.0)
    return {k: (v - low) / (high - low) for k, v in scores.items()}


class HybridRetriever:
    """Ranks the chunks of one assessment for a query.

    Without an embedder (or with empty vectors, as the ``none`` provider returns) only BM25 counts
    and ``embedding_weight`` is ignored. Otherwise the score is the weighted mean of the two
    normalised signals, so it stays within [0, 1] and ``min_score`` keeps its meaning.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        tokenizer: Tokenizer,
        embedder: Embedder | None,
        settings: RetrievalSettings,
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._chunks = {c.chunk_id: c for c in chunks}
        self._bm25 = Bm25Index(chunks, tokenizer, settings)
        self._vectors: VectorIndex | None = None
        if embedder is not None and chunks:
            vectors = embedder.embed_documents([c.text for c in chunks])
            if all(len(v) > 0 for v in vectors):
                self._vectors = VectorIndex(chunks, vectors)

    def retrieve(self, query: str, top_k: int | None = None) -> list[ScoredChunk]:
        """Best chunks first (ties by chunk ID), at most ``top_k`` (default ``retrieval.top_k``)."""
        limit = self._settings.top_k if top_k is None else top_k
        bm25 = min_max(self._bm25.scores(query))
        vector = None
        if self._vectors is not None and self._embedder is not None:
            vector = min_max(self._vectors.scores(self._embedder.embed_query(query)))
        weights = self._settings.bm25_weight, self._settings.embedding_weight
        results: list[ScoredChunk] = []
        for cid, chunk in self._chunks.items():
            if vector is None:
                score = bm25[cid]
            else:
                score = (weights[0] * bm25[cid] + weights[1] * vector[cid]) / sum(weights)
            score = round(score, FLOAT_DECIMALS)
            if score >= self._settings.min_score:
                results.append(
                    ScoredChunk(
                        chunk=chunk,
                        score=score,
                        bm25=round(bm25[cid], FLOAT_DECIMALS),
                        vector=None if vector is None else round(vector[cid], FLOAT_DECIMALS),
                    )
                )
        results.sort(key=lambda r: (-r.score, r.chunk.chunk_id))
        return results[:limit]

    def for_control(self, control: Control, top_k: int | None = None) -> list[ScoredChunk]:
        """Retrieve with the query built from the control (title, requirement, keywords)."""
        return self.retrieve(build_query(control), top_k)


__all__ = ["HybridRetriever", "min_max"]
