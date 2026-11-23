"""BM25 index: ranking, deterministic tie-breaking, edge cases, cross-process stability."""

import os
import random
import subprocess
import sys
from collections.abc import Callable

import pytest

from vendorguard.config import Settings
from vendorguard.models.evidence import Chunk
from vendorguard.retrieval.bm25_index import Bm25Index
from vendorguard.retrieval.tokenizer import Tokenizer


def _chunk(cid: str, text: str) -> Chunk:
    return Chunk(chunk_id=cid, doc_id="d", page=1, text=text, char_start=0, char_end=len(text))


@pytest.fixture
def build(settings_override: Callable[..., Settings]) -> Callable[..., Bm25Index]:
    s = settings_override().retrieval

    def make(chunks: list[Chunk]) -> Bm25Index:
        return Bm25Index(chunks, Tokenizer(s.stop_words), s)

    return make


CORPUS = [
    _chunk(
        "c:p001:c000", "Multi-factor authentication is enforced for all staff and administrators."
    ),
    _chunk(
        "c:p002:c000", "Backups are encrypted and stored offsite, and restore tests run yearly."
    ),
    _chunk("c:p003:c000", "A penetration test is performed every year by an independent firm."),
    _chunk("c:p004:c000", "Employees can join running and chess clubs and social events."),
    _chunk(
        "c:p005:c000", "Network segmentation and a firewall protect the production environment."
    ),
    _chunk("c:p006:c000", "Customer data is encrypted at rest and keys are managed centrally."),
]


def test_the_matching_chunk_ranks_first(build: Callable[..., Bm25Index]) -> None:
    index = build(CORPUS)
    assert index.search("multi-factor authentication MFA")[0].chunk.chunk_id == "c:p001:c000"
    assert index.search("penetration test independent")[0].chunk.chunk_id == "c:p003:c000"
    assert index.search("backups offsite restore")[0].chunk.chunk_id == "c:p002:c000"


def test_more_matching_terms_rank_higher(build: Callable[..., Bm25Index]) -> None:
    index = build(CORPUS)
    ranked = [h.chunk.chunk_id for h in index.search("customer data encrypted at rest keys")]
    assert ranked.index("c:p006:c000") < ranked.index("c:p002:c000")


def test_chunks_without_a_matching_term_are_not_returned(build: Callable[..., Bm25Index]) -> None:
    hits = build(CORPUS).search("firewall segmentation")
    assert [h.chunk.chunk_id for h in hits] == ["c:p005:c000"]
    assert build(CORPUS).search("zzzz unknown") == []


def test_equal_scores_are_ordered_by_chunk_id_whatever_the_input_order(
    build: Callable[..., Bm25Index],
) -> None:
    twins = [_chunk(f"t:p{n:03d}:c000", "backup restore test offsite") for n in range(1, 8)]
    for seed in range(6):
        shuffled = twins[:]
        random.Random(seed).shuffle(shuffled)
        hits = build([*shuffled, CORPUS[0]]).search("backup restore")
        assert [h.chunk.chunk_id for h in hits] == sorted(t.chunk_id for t in twins)
        assert len({h.score for h in hits}) == 1


def test_results_do_not_depend_on_input_order(build: Callable[..., Bm25Index]) -> None:
    forward = build(CORPUS).search("encrypted data keys backups")
    backward = build(CORPUS[::-1]).search("encrypted data keys backups")
    assert forward == backward


def test_scores_are_rounded_to_six_decimals_and_not_negative(
    build: Callable[..., Bm25Index],
) -> None:
    for score in build(CORPUS).scores("encrypted data backups firewall").values():
        assert score >= 0 and score == round(score, 6)


def test_scores_covers_every_chunk_with_zero_for_misses(build: Callable[..., Bm25Index]) -> None:
    scores = build(CORPUS).scores("firewall")
    assert sorted(scores) == sorted(c.chunk_id for c in CORPUS)
    assert scores["c:p005:c000"] > 0 and scores["c:p004:c000"] == 0.0


def test_top_k_limits_and_keeps_the_best(build: Callable[..., Bm25Index]) -> None:
    index = build(CORPUS)
    query = "authentication backups penetration firewall"
    everything = index.search(query)
    assert len(everything) == 4
    assert index.search(query, top_k=2) == everything[:2]
    assert index.search("encrypted", top_k=0) == []


def test_empty_query_empty_corpus_and_stop_word_only_inputs(
    build: Callable[..., Bm25Index],
) -> None:
    assert build(CORPUS).search("") == []
    assert build(CORPUS).search("the and of") == []
    assert build([]).search("anything") == []
    assert build([]).scores("anything") == {}
    only_stop = build([_chunk("s:p001:c000", "the and of")])
    assert only_stop.search("the") == [] and only_stop.scores("policy") == {"s:p001:c000": 0.0}


def test_duplicate_chunk_ids_are_rejected(build: Callable[..., Bm25Index]) -> None:
    with pytest.raises(ValueError, match="unique"):
        build([CORPUS[0], CORPUS[0]])


def test_a_single_chunk_corpus_still_finds_its_matches(build: Callable[..., Bm25Index]) -> None:
    """Okapi BM25 scores such a match below zero; BM25+ must report it as a hit."""
    hits = build([CORPUS[0]]).search("authentication")
    assert len(hits) == 1 and hits[0].score > 0
    assert build([CORPUS[0]]).search("firewall") == []


def test_a_two_chunk_corpus_ranks_the_matching_chunk_first(build: Callable[..., Bm25Index]) -> None:
    hits = build([CORPUS[0], CORPUS[4]]).search("firewall segmentation")
    assert [h.chunk.chunk_id for h in hits] == ["c:p005:c000"]
    assert all(h.score > 0 for h in hits)


def test_repeated_query_terms_are_deterministic(build: Callable[..., Bm25Index]) -> None:
    index = build(CORPUS)
    assert index.search("backups backups offsite") == index.search("backups backups offsite")


def test_bm25_parameters_come_from_settings(settings_override: Callable[..., Settings]) -> None:
    def top_score(b: float) -> float:
        s = settings_override(retrieval={"bm25_b": b}).retrieval
        return Bm25Index(CORPUS, Tokenizer(s.stop_words), s).scores("backups offsite")[
            "c:p002:c000"
        ]

    assert top_score(0.0) != top_score(1.0)


_SCRIPT = """
import json
from vendorguard.config import load_settings
from vendorguard.models.evidence import Chunk
from vendorguard.retrieval.bm25_index import Bm25Index
from vendorguard.retrieval.tokenizer import Tokenizer

s = load_settings(env_file=None).retrieval
texts = [
    "MFA is enforced for all staff and administrators.",
    "Backups are stored offsite.",
    "Backups are encrypted and restore tests run yearly.",
    "Firewall and network segmentation.",
] * 5
chunks = [
    Chunk(chunk_id=f"x:p{i:03d}:c000", doc_id="d", page=1, text=t, char_start=0, char_end=len(t))
    for i, t in enumerate(texts)
]
index = Bm25Index(chunks, Tokenizer(s.stop_words), s)
print(json.dumps(index.scores("backups offsite mfa"), sort_keys=True))
"""


def test_scores_are_identical_across_processes_and_hash_seeds() -> None:
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


def test_a_term_found_in_every_chunk_still_scores_positively(
    build: Callable[..., Bm25Index],
) -> None:
    """Okapi IDF would make this negative; a match must never score below a chunk without it."""
    chunks = [_chunk(f"k:p{n:03d}:c000", f"policy item {n}") for n in range(1, 6)]
    chunks.append(_chunk("k:p006:c000", "unrelated words only"))
    scores = build(chunks).scores("policy")
    assert all(scores[f"k:p{n:03d}:c000"] > 0 for n in range(1, 6))
    assert scores["k:p006:c000"] == 0.0
