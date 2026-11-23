"""Hybrid retrieval: BM25 and (optionally) embedding similarity, each scaled to [0, 1]."""

from collections.abc import Sequence

from vendorguard.config_models.core import RetrievalSettings
from vendorguard.errors import EmbeddingError
from vendorguard.interfaces.embedder import Embedder
from vendorguard.models.control import Control
from vendorguard.models.evidence import Chunk, ScoredChunk
from vendorguard.retrieval.bm25_index import Bm25Index
from vendorguard.retrieval.query_builder import build_query
from vendorguard.retrieval.tokenizer import Tokenizer
from vendorguard.retrieval.vector_index import VectorIndex
from vendorguard.utils.jsonio import FLOAT_DECIMALS


def scale_to_unit(scores: dict[str, float]) -> dict[str, float]:
    """Scale scores into [0, 1] by the best score, keeping zero at zero.

    Plain min-max would turn the weakest real match into 0.0 and let ``min_score`` discard it. So
    the floor is ``min(0, lowest)``: BM25 scores (never below 0) are divided by the maximum, and
    cosine similarities are shifted only when some are negative. When nothing rises above the floor
    (all zero, or all equal and not positive) there is no signal and every score is 0.0. All-equal
    positive scores are a uniform signal and become 1.0.
    """
    if not scores:
        return {}
    high, floor = max(scores.values()), min(0.0, min(scores.values()))
    span = high - floor
    if span <= 0:
        return dict.fromkeys(scores, 0.0)
    return {key: (value - floor) / span for key, value in scores.items()}


class HybridRetriever:
    """Ranks the chunks of one assessment for a query.

    Without an embedder (or with empty vectors, as the ``none`` provider returns) only BM25 counts
    and ``embedding_weight`` is ignored. Otherwise the score is the weighted mean of the two scaled
    signals, so it stays within [0, 1]. ``score`` and ``min_score`` are relative to the best chunk
    of the query; absolute relevance is in the ``bm25_raw`` and ``vector_raw`` of each result.
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
                try:
                    self._vectors = VectorIndex(chunks, vectors)
                except ValueError as exc:
                    raise EmbeddingError(f"the embedder returned unusable vectors: {exc}") from exc

    def retrieve(self, query: str, top_k: int | None = None) -> list[ScoredChunk]:
        """Best chunks first (ties by chunk ID), at most ``top_k`` (default ``retrieval.top_k``)."""
        limit = self._settings.top_k if top_k is None else top_k
        if limit < 0:
            raise ValueError("top_k must not be negative")
        bm25_raw = self._bm25.scores(query)
        bm25 = scale_to_unit(bm25_raw)
        vector_raw: dict[str, float] | None = None
        if self._vectors is not None and self._embedder is not None:
            try:
                vector_raw = self._vectors.scores(self._embedder.embed_query(query))
            except ValueError as exc:
                raise EmbeddingError(f"the query vector does not fit the index: {exc}") from exc
        vector = None if vector_raw is None else scale_to_unit(vector_raw)
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
                        bm25_raw=bm25_raw[cid],
                        vector_raw=None if vector_raw is None else vector_raw[cid],
                    )
                )
        results.sort(key=lambda r: (-r.score, r.chunk.chunk_id))
        return results[:limit]

    def for_control(self, control: Control, top_k: int | None = None) -> list[ScoredChunk]:
        """Retrieve with the query built from the control (title, requirement, keywords)."""
        return self.retrieve(build_query(control), top_k)


__all__ = ["HybridRetriever", "scale_to_unit"]
