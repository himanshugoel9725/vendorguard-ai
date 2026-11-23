"""Seeded property-style tests for BM25 and hybrid retrieval over random corpora."""

import random
from collections.abc import Callable, Sequence

import pytest

from vendorguard.config import Settings
from vendorguard.models.evidence import Chunk
from vendorguard.providers.embed.null import NullEmbedder
from vendorguard.retrieval.bm25_index import Bm25Index
from vendorguard.retrieval.hybrid import HybridRetriever
from vendorguard.retrieval.tokenizer import Tokenizer

SEEDS = list(range(12))
VOCAB = [f"zq{n}" for n in range(14)]


class VocabEmbedder:
    """Deterministic term-count vectors over VOCAB."""

    def _vec(self, text: str) -> list[float]:
        words = text.split()
        return [float(words.count(w)) + 0.01 for w in VOCAB]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def _corpus(seed: int, size: int | None = None) -> list[Chunk]:
    rng = random.Random(seed)
    chunks = []
    for i in range(size or rng.randint(3, 12)):
        text = " ".join(rng.choice(VOCAB) for _ in range(rng.randint(1, 15)))
        chunks.append(
            Chunk(
                chunk_id=f"r:p{i:03d}:c000",
                doc_id="r",
                page=1,
                text=text,
                char_start=0,
                char_end=len(text),
            )
        )
    return chunks


def _query(seed: int) -> str:
    rng = random.Random(seed + 1000)
    return " ".join(rng.sample(VOCAB, rng.randint(1, 4)))


@pytest.fixture
def cfg(settings_override: Callable[..., Settings]) -> Callable[..., tuple[Tokenizer, object]]:
    def make(**retrieval: object) -> tuple[Tokenizer, object]:
        s = settings_override(retrieval=retrieval).retrieval
        return Tokenizer(s.stop_words), s

    return make


def _bm25(cfg: Callable[..., tuple[Tokenizer, object]], chunks: list[Chunk]) -> Bm25Index:
    tok, s = cfg()
    return Bm25Index(chunks, tok, s)  # type: ignore[arg-type]


def _hybrid(
    cfg: Callable[..., tuple[Tokenizer, object]],
    chunks: list[Chunk],
    embedder: object | None,
    **retrieval: object,
) -> HybridRetriever:
    tok, s = cfg(**retrieval)
    return HybridRetriever(chunks, tok, embedder, s)  # type: ignore[arg-type]


@pytest.mark.parametrize("seed", SEEDS)
def test_bm25_scores_are_non_negative_and_zero_without_shared_tokens(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    scores = _bm25(cfg, chunks).scores(query)
    qtokens = set(query.split())
    for c in chunks:
        assert scores[c.chunk_id] >= 0.0
        if not qtokens & set(c.text.split()):
            assert scores[c.chunk_id] == 0.0


@pytest.mark.parametrize("seed", SEEDS)
def test_a_chunk_with_all_query_tokens_never_scores_below_one_with_none(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    n = len(chunks)
    full = Chunk(chunk_id="r:p900:c000", doc_id="r", page=1, text=query, char_start=0, char_end=1)
    none = Chunk(chunk_id="r:p901:c000", doc_id="r", page=1, text="other", char_start=0, char_end=5)
    scores = _bm25(cfg, [*chunks[:n], full, none]).scores(query)
    assert scores[full.chunk_id] >= scores[none.chunk_id] == 0.0
    assert scores[full.chunk_id] > 0


@pytest.mark.parametrize("seed", SEEDS)
def test_input_permutation_does_not_change_scores_or_search(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    shuffled = chunks[:]
    random.Random(seed).shuffle(shuffled)
    a, b = _bm25(cfg, chunks), _bm25(cfg, shuffled)
    assert a.scores(query) == b.scores(query)
    assert a.search(query) == b.search(query)


@pytest.mark.parametrize("seed", SEEDS)
def test_search_top_k_is_a_prefix_of_the_full_ranking(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    index, query = _bm25(cfg, _corpus(seed)), _query(seed)
    full = index.search(query)
    for k in range(len(full) + 2):
        assert index.search(query, top_k=k) == full[:k]


@pytest.mark.parametrize("seed", SEEDS)
def test_adding_an_unrelated_chunk_keeps_matches_positive(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    before = _bm25(cfg, chunks).scores(query)
    extra = Chunk(
        chunk_id="r:p999:c000", doc_id="r", page=1, text="filler", char_start=0, char_end=6
    )
    after = _bm25(cfg, [*chunks, extra]).scores(query)
    for cid, score in before.items():
        if score > 0:
            assert after[cid] > 0
    assert after[extra.chunk_id] == 0.0


@pytest.mark.parametrize("seed", SEEDS)
def test_repeating_a_query_token_does_not_lower_the_best_score(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    index, query = _bm25(cfg, _corpus(seed)), _query(seed)
    base = max(index.scores(query).values())
    repeated = max(index.scores(f"{query} {query.split()[0]}").values())
    assert repeated >= base


@pytest.mark.parametrize("seed", SEEDS)
def test_rebuilding_the_same_corpus_gives_the_same_ranks(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    assert _bm25(cfg, chunks).search(query) == _bm25(cfg, list(chunks)).search(query)


@pytest.mark.parametrize("seed", SEEDS)
def test_hybrid_scores_are_in_unit_range_sorted_and_bounded(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    top_k = random.Random(seed).randint(1, 5)
    hits = _hybrid(cfg, chunks, VocabEmbedder(), min_score=0.0).retrieve(query, top_k)
    assert len(hits) <= top_k
    assert all(0.0 <= h.score <= 1.0 for h in hits)
    keys = [(-h.score, h.chunk.chunk_id) for h in hits]
    assert keys == sorted(keys)


@pytest.mark.parametrize("seed", SEEDS)
def test_extreme_weights_follow_one_signal(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    lex = _hybrid(
        cfg, chunks, VocabEmbedder(), bm25_weight=1.0, embedding_weight=0.0, min_score=0.0
    )
    vec = _hybrid(
        cfg, chunks, VocabEmbedder(), bm25_weight=0.0, embedding_weight=1.0, min_score=0.0
    )
    lex_hits, vec_hits = lex.retrieve(query, 50), vec.retrieve(query, 50)
    assert [h.chunk.chunk_id for h in lex_hits] == [
        h.chunk.chunk_id for h in sorted(lex_hits, key=lambda h: (-h.bm25, h.chunk.chunk_id))
    ]
    assert all(h.vector is not None for h in vec_hits)
    assert [h.chunk.chunk_id for h in vec_hits] == [
        h.chunk.chunk_id
        for h in sorted(vec_hits, key=lambda h: (-(h.vector or 0.0), h.chunk.chunk_id))
    ]


@pytest.mark.parametrize("seed", SEEDS)
def test_equal_weights_give_the_mean_and_min_score_one_keeps_only_perfect_hits(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    equal = dict(bm25_weight=0.5, embedding_weight=0.5)
    for h in _hybrid(cfg, chunks, VocabEmbedder(), min_score=0.0, **equal).retrieve(query, 50):
        assert h.vector is not None
        assert h.score == pytest.approx(0.5 * h.bm25 + 0.5 * h.vector, abs=2e-6)
    strict = _hybrid(cfg, chunks, VocabEmbedder(), min_score=1.0, **equal).retrieve(query, 50)
    assert all(h.score == 1.0 for h in strict)


@pytest.mark.parametrize("seed", SEEDS)
def test_no_embedder_equals_the_null_embedder(
    seed: int, cfg: Callable[..., tuple[Tokenizer, object]]
) -> None:
    chunks, query = _corpus(seed), _query(seed)
    assert _hybrid(cfg, chunks, None).retrieve(query, 20) == _hybrid(
        cfg, chunks, NullEmbedder()
    ).retrieve(query, 20)
