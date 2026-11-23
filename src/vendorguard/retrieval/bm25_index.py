"""BM25 ranking of chunks. Ties are broken by chunk ID, so results never depend on input order.

The classic Okapi IDF, ``log((N - df + 0.5) / (df + 0.5))``, turns negative for terms found in more
than half of the chunks and makes every match negative in a tiny corpus (a one-page document), so
real matches would be reported as misses. The Lucene/Elasticsearch form ``log(1 + (N - df + 0.5) /
(df + 0.5))`` is always positive; a chunk without the term still scores 0.
"""

import math
from collections.abc import Sequence
from typing import NamedTuple

from rank_bm25 import BM25Okapi

from vendorguard.config_models.core import RetrievalSettings
from vendorguard.models.evidence import Chunk
from vendorguard.retrieval.tokenizer import Tokenizer
from vendorguard.utils.jsonio import FLOAT_DECIMALS


class _PositiveIdfBm25(BM25Okapi):  # type: ignore[misc]  # rank-bm25 has no type stubs
    """Okapi BM25 with the always-positive Lucene IDF (overrides the library's IDF hook)."""

    def _calc_idf(self, nd: dict[str, int]) -> None:
        for word, freq in nd.items():
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))


class Hit(NamedTuple):
    """A chunk with its BM25 score."""

    chunk: Chunk
    score: float


class Bm25Index:
    """An in-memory BM25 index over a fixed list of chunks."""

    def __init__(
        self, chunks: Sequence[Chunk], tokenizer: Tokenizer, settings: RetrievalSettings
    ) -> None:
        self._chunks = sorted(chunks, key=lambda c: c.chunk_id)
        ids = [c.chunk_id for c in self._chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("chunk IDs must be unique")
        self._tokenizer = tokenizer
        corpus = [tokenizer.tokenize(c.text) for c in self._chunks]
        # BM25 divides by the average length, so a corpus without any token cannot be ranked
        self._bm25 = (
            _PositiveIdfBm25(corpus, k1=settings.bm25_k1, b=settings.bm25_b)
            if any(corpus)
            else None
        )

    def scores(self, query: str) -> dict[str, float]:
        """Score of every chunk for ``query`` (0.0 when nothing matches), keyed by chunk ID."""
        tokens = self._tokenizer.tokenize(query)
        if self._bm25 is None or not tokens:
            return {c.chunk_id: 0.0 for c in self._chunks}
        raw = self._bm25.get_scores(tokens)
        return {
            c.chunk_id: round(float(score), FLOAT_DECIMALS) + 0.0
            for c, score in zip(self._chunks, raw, strict=True)
        }

    def search(self, query: str, top_k: int | None = None) -> list[Hit]:
        """Chunks with a positive score, best first, ties by chunk ID; at most ``top_k``."""
        by_id = {c.chunk_id: c for c in self._chunks}
        ranked = sorted(
            ((cid, score) for cid, score in self.scores(query).items() if score > 0),
            key=lambda item: (-item[1], item[0]),
        )
        hits = [Hit(by_id[cid], score) for cid, score in ranked]
        return hits if top_k is None else hits[:top_k]


__all__ = ["Bm25Index", "Hit"]
