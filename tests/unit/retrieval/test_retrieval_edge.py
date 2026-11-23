"""Edge cases for the tokenizer, vector index, hybrid retriever, query builder, determinism."""

import math
import os
import random
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import EmbeddingError
from vendorguard.models.evidence import Chunk
from vendorguard.retrieval.hybrid import HybridRetriever
from vendorguard.retrieval.query_builder import build_query
from vendorguard.retrieval.tokenizer import Tokenizer
from vendorguard.retrieval.vector_index import VectorIndex


def _chunk(cid: str, text: str = "x") -> Chunk:
    return Chunk(chunk_id=cid, doc_id="d", page=1, text=text, char_start=0, char_end=len(text))


def _chunks(n: int) -> list[Chunk]:
    return [_chunk(f"v:p{i:03d}:c000") for i in range(n)]


# --- tokenizer --------------------------------------------------------------------------------


def test_tokenizer_very_long_text_and_digits_only() -> None:
    tok = Tokenizer([])
    assert len(tok.tokenize("word " * 100_000)) == 100_000
    assert tok.tokenize("2024 12345 007") == ["2024", "12345", "007"]


def test_tokens_never_contain_underscores_or_punctuation() -> None:
    tokens = Tokenizer([]).tokenize("snake_case, a.b; c!d? (e) [f] {g} 'h' \"i\" x_y_z-1")
    assert tokens == [
        "snake",
        "case",
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "x",
        "y",
        "z",
        "1",
    ]
    assert all(t.isalnum() for t in tokens)


def test_mixed_scripts_are_kept() -> None:
    assert Tokenizer([]).tokenize("Straße 数据 Данные café") == ["straße", "数据", "данные", "café"]


def test_nfc_and_nfd_give_different_tokens_today() -> None:
    """Documents current behaviour: combining marks are not alphanumeric, so NFD text is split."""
    nfc, nfd = "café", "café"
    tok = Tokenizer([])
    assert tok.tokenize(nfc) == ["café"]
    assert tok.tokenize(nfd) != tok.tokenize(nfc)


def test_stop_words_are_lower_cased_but_not_stripped() -> None:
    tok = Tokenizer(["The", " and "])
    assert tok.tokenize("the AND and x") == ["and", "and", "x"]


# --- vector index -----------------------------------------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def test_many_chunks_agree_with_plain_python_cosine() -> None:
    rng = random.Random(7)
    chunks = _chunks(500)
    vectors = [[rng.uniform(-1, 1) for _ in range(16)] for _ in chunks]
    query = [rng.uniform(-1, 1) for _ in range(16)]
    scores = VectorIndex(chunks, vectors).scores(query)
    for c, v in zip(chunks, vectors, strict=True):
        assert scores[c.chunk_id] == pytest.approx(_cosine(v, query), abs=1e-6)


def test_one_dimensional_and_integer_vectors() -> None:
    idx = VectorIndex(_chunks(3), [[2], [-3], [0]])
    assert idx.scores([5]) == {"v:p000:c000": 1.0, "v:p001:c000": -1.0, "v:p002:c000": 0.0}


@pytest.mark.parametrize("scale", [1e-12, 1e12])
def test_extreme_magnitudes_do_not_overflow_or_give_nan(scale: float) -> None:
    idx = VectorIndex(_chunks(2), [[scale, scale], [scale, -scale]])
    scores = idx.scores([scale, 0.0])
    assert all(math.isfinite(s) for s in scores.values())
    assert scores["v:p000:c000"] == pytest.approx(math.sqrt(0.5), abs=1e-6)


# --- hybrid retriever -------------------------------------------------------------------------


class CountingEmbedder:
    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self.docs = 0
        self.queries = 0
        self._vectors = vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.docs += 1
        return (
            self._vectors
            if self._vectors is not None
            else [[1.0, float(i)] for i, _ in enumerate(texts)]
        )

    def embed_query(self, text: str) -> list[float]:
        self.queries += 1
        return [1.0, 1.0]


TEXTS = ["alpha beta", "beta gamma", "gamma delta"]
DOCS = [_chunk(f"h:p{i:03d}:c000", t) for i, t in enumerate(TEXTS)]


def _retriever(
    settings_override: Callable[..., Settings], embedder: object | None
) -> HybridRetriever:
    s = settings_override(retrieval={"top_k": 3}).retrieval
    return HybridRetriever(DOCS, Tokenizer(s.stop_words), embedder, s)  # type: ignore[arg-type]


def test_embedder_is_called_once_at_build_and_once_per_query(
    settings_override: Callable[..., Settings],
) -> None:
    emb = CountingEmbedder()
    r = _retriever(settings_override, emb)
    assert (emb.docs, emb.queries) == (1, 0)
    r.retrieve("beta")
    r.retrieve("gamma")
    assert (emb.docs, emb.queries) == (1, 2)


def test_empty_vectors_disable_the_vector_signal(
    settings_override: Callable[..., Settings],
) -> None:
    emb = CountingEmbedder([[], [], []])
    r = _retriever(settings_override, emb)
    hits = r.retrieve("beta")
    assert hits and all(h.vector is None for h in hits)
    assert emb.queries == 0


def test_wrong_vector_count_raises_embedding_error(
    settings_override: Callable[..., Settings],
) -> None:
    with pytest.raises(EmbeddingError, match="one vector per chunk"):
        _retriever(settings_override, CountingEmbedder([[1.0, 2.0]]))


def test_for_control_matches_retrieve_of_the_built_query(
    settings_override: Callable[..., Settings], project_root: Path
) -> None:
    s = settings_override()
    control = load_controls(project_root / s.paths.controls_file).controls[0]
    r = _retriever(settings_override, None)
    assert r.for_control(control) == r.retrieve(build_query(control))
    assert r.for_control(control, 1) == r.retrieve(build_query(control), 1)


# --- query builder ----------------------------------------------------------------------------


def test_every_baseline_control_builds_a_usable_query(
    settings_override: Callable[..., Settings], project_root: Path
) -> None:
    s = settings_override()
    controls = load_controls(project_root / s.paths.controls_file).controls
    assert len(controls) == 25
    tok = Tokenizer(s.retrieval.stop_words)
    for control in controls:
        q = build_query(control)
        assert q.strip() and "\n" not in q
        assert len(tok.tokenize(q)) >= 8


# --- cross-process determinism ----------------------------------------------------------------

_SCRIPT = """
import json
from vendorguard.config import load_settings
from vendorguard.models.evidence import Chunk
from vendorguard.retrieval.bm25_index import Bm25Index
from vendorguard.retrieval.hybrid import HybridRetriever
from vendorguard.retrieval.tokenizer import Tokenizer

class Emb:
    def _v(self, t):
        return [t.count(w) + 0.5 for w in ("backup", "mfa", "firewall")]
    def embed_documents(self, texts):
        return [self._v(t.lower()) for t in texts]
    def embed_query(self, t):
        return self._v(t.lower())

s = load_settings(env_file=None).retrieval
texts = [
    "MFA is enforced for all staff.",
    "Backups are stored offsite.",
    "Backup restore tests run yearly.",
    "Firewall and network segmentation.",
] * 5
chunks = [
    Chunk(chunk_id=f"x:p{i:03d}:c000", doc_id="d", page=1, text=t, char_start=0, char_end=len(t))
    for i, t in enumerate(texts)
]
tok = Tokenizer(s.stop_words)
q = "backup offsite mfa"
out = {
    "bm25": Bm25Index(chunks, tok, s).scores(q),
    "hybrid": [
        (h.chunk.chunk_id, h.score, h.bm25, h.vector)
        for h in HybridRetriever(chunks, tok, Emb(), s).retrieve(q, 30)
    ],
}
print(json.dumps(out, sort_keys=True))
"""


def test_bm25_and_hybrid_scores_are_identical_across_hash_seeds() -> None:
    outputs = {
        subprocess.run(
            [sys.executable, "-c", _SCRIPT],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("0", "1", "42", "random")
    }
    assert len(outputs) == 1
