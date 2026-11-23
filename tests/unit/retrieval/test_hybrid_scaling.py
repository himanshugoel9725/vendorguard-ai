"""Phase 3 review fixes: weak matches survive scaling, raw signals are exposed, inputs validated."""

from collections.abc import Callable, Sequence

import pytest

from vendorguard.config import Settings
from vendorguard.errors import EmbeddingError
from vendorguard.models.evidence import Chunk
from vendorguard.retrieval.hybrid import HybridRetriever, scale_to_unit
from vendorguard.retrieval.tokenizer import Tokenizer


def _chunk(cid: str, text: str) -> Chunk:
    return Chunk(chunk_id=cid, doc_id="d", page=1, text=text, char_start=0, char_end=len(text))


# Every chunk mentions the query terms, with very different strength (the reviewer's scenario).
MATCHING = [
    _chunk(
        "m:p001:c000", "MFA and access control: MFA is required, MFA is audited, access is logged."
    ),
    _chunk(
        "m:p002:c000", "Access reviews happen yearly and cover many unrelated systems and teams."
    ),
    _chunk("m:p003:c000", "A long section about office life that mentions MFA once, in passing."),
    _chunk("m:p004:c000", "Nothing relevant: canteen menu and garden furniture."),
]


class FixedEmbedder:
    """Returns the given query vector; document vectors are one-hot by position."""

    model = "fixed"

    def __init__(self, query: Sequence[float], dims: int = 3) -> None:
        self._query, self._dims = list(query), dims

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [1.0 if i == n % self._dims else 0.0 for i in range(self._dims)]
            for n, _ in enumerate(texts)
        ]

    def embed_query(self, text: str) -> list[float]:
        return self._query


@pytest.fixture
def retriever(settings_override: Callable[..., Settings]) -> Callable[..., HybridRetriever]:
    def build(embedder: object | None = None, **retrieval: object) -> HybridRetriever:
        s = settings_override(retrieval=retrieval).retrieval
        return HybridRetriever(MATCHING, Tokenizer(s.stop_words), embedder, s)  # type: ignore[arg-type]

    return build


def test_every_chunk_that_matches_is_returned_even_the_weakest(
    retriever: Callable[..., HybridRetriever],
) -> None:
    """Plain min-max mapped the weakest match to 0.0 and min_score dropped it."""
    hits = retriever().retrieve("MFA access", top_k=10)
    assert [h.chunk.chunk_id for h in hits] == ["m:p001:c000", "m:p002:c000", "m:p003:c000"]
    assert all(h.score > 0 for h in hits) and hits[0].score == 1.0
    assert hits[-1].score >= retriever().retrieve("MFA access", 10)[-1].score > 0


def test_a_chunk_with_no_matching_term_is_still_excluded(
    retriever: Callable[..., HybridRetriever],
) -> None:
    assert "m:p004:c000" not in {h.chunk.chunk_id for h in retriever().retrieve("MFA access", 10)}


def test_raw_bm25_is_exposed_and_vector_raw_is_none_without_vectors(
    retriever: Callable[..., HybridRetriever],
) -> None:
    hits = retriever().retrieve("MFA access", 10)
    assert all(h.bm25_raw > 0 and h.vector_raw is None for h in hits)
    assert [h.bm25_raw for h in hits] == sorted((h.bm25_raw for h in hits), reverse=True)
    assert hits[0].bm25 == 1.0 and hits[0].bm25_raw != 1.0  # scaled and raw are different things


def test_raw_cosine_is_exposed_with_vectors(retriever: Callable[..., HybridRetriever]) -> None:
    hits = retriever(FixedEmbedder([1.0, 0.0, 0.0])).retrieve("MFA access", 10)
    by_id = {h.chunk.chunk_id: h for h in hits}
    assert by_id["m:p001:c000"].vector_raw == 1.0  # chunk 0 is the one-hot [1, 0, 0]
    assert all(h.vector_raw is not None and -1.0 <= h.vector_raw <= 1.0 for h in hits)


def test_a_negative_top_k_is_an_error_not_a_silent_slice(
    retriever: Callable[..., HybridRetriever],
) -> None:
    with pytest.raises(ValueError, match="negative"):
        retriever().retrieve("MFA", top_k=-1)


def test_a_query_vector_of_the_wrong_dimension_is_an_embedding_error(
    retriever: Callable[..., HybridRetriever],
) -> None:
    with pytest.raises(EmbeddingError, match="query vector"):
        retriever(FixedEmbedder([1.0, 0.0, 0.0, 0.0])).retrieve("MFA")


def test_scaling_does_not_amplify_a_tiny_cosine_spread() -> None:
    """Min-max turned 0.81 vs 0.82 into 0 vs 1; the zero-floored scale keeps them close."""
    scaled = scale_to_unit({"a": 0.81, "b": 0.82})
    assert scaled["b"] == 1.0 and scaled["a"] == pytest.approx(0.9878, abs=1e-3)


def test_scaling_shifts_only_when_some_scores_are_negative() -> None:
    assert scale_to_unit({"a": -0.5, "b": 0.0, "c": 0.5}) == {"a": 0.0, "b": 0.5, "c": 1.0}
    assert scale_to_unit({"a": 0.2, "b": 0.4}) == {"a": 0.5, "b": 1.0}
    assert scale_to_unit({"a": -0.3, "b": -0.3}) == {"a": 0.0, "b": 0.0}
