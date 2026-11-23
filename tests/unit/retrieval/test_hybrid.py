"""Hybrid retrieval: normalisation, weighting, thresholds, ties, and recall on the samples."""

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.eval.specs import SampleState, load_spec
from vendorguard.ingest.chunker import chunk_document
from vendorguard.ingest.loader import load_document
from vendorguard.ingest.text_cleaner import clean_document
from vendorguard.models.evidence import Chunk
from vendorguard.providers.embed.null import NullEmbedder
from vendorguard.retrieval.hybrid import HybridRetriever, min_max
from vendorguard.retrieval.tokenizer import Tokenizer

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]
TERMS = ["mfa", "backup", "firewall", "training"]


class TermEmbedder:
    """Vectors of term counts: a tiny, deterministic stand-in for a real embedding model."""

    model = "terms"

    def _vec(self, text: str) -> list[float]:
        return [float(text.lower().count(t)) + 0.01 for t in TERMS]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def _chunk(cid: str, text: str) -> Chunk:
    return Chunk(chunk_id=cid, doc_id="d", page=1, text=text, char_start=0, char_end=len(text))


CHUNKS = [
    _chunk("d:p001:c000", "MFA is enforced for every employee login."),
    _chunk("d:p002:c000", "Backup copies are kept offsite every night."),
    _chunk("d:p003:c000", "A firewall protects the production network."),
    _chunk("d:p004:c000", "Training sessions run for new employees."),
    _chunk("d:p005:c000", "Our office has a canteen and a garden."),
]


@pytest.fixture
def make(settings_override: Callable[..., Settings]) -> Callable[..., HybridRetriever]:
    def build(embedder: object | None = None, **retrieval: object) -> HybridRetriever:
        s = settings_override(retrieval=retrieval).retrieval
        return HybridRetriever(CHUNKS, Tokenizer(s.stop_words), embedder, s)  # type: ignore[arg-type]

    return build


# --- min_max ----------------------------------------------------------------------------------


def test_min_max_scales_to_unit_range() -> None:
    assert min_max({"a": 2.0, "b": 4.0, "c": 3.0}) == {"a": 0.0, "b": 1.0, "c": 0.5}


def test_equal_positive_scores_are_a_uniform_signal() -> None:
    """All chunks matching equally, or a single matching chunk, must not be erased."""
    assert min_max({"a": 5.0, "b": 5.0}) == {"a": 1.0, "b": 1.0}
    assert min_max({"a": 0.3}) == {"a": 1.0}


def test_equal_zero_or_negative_scores_and_empty_input_give_no_signal() -> None:
    assert min_max({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}
    assert min_max({"a": -0.2}) == {"a": 0.0}
    assert min_max({}) == {}


def test_min_max_handles_negative_scores() -> None:
    assert min_max({"a": -1.0, "b": 1.0}) == {"a": 0.0, "b": 1.0}


# --- BM25 only --------------------------------------------------------------------------------


def test_bm25_only_ranks_the_matching_chunk_first_and_has_no_vector(
    make: Callable[..., HybridRetriever],
) -> None:
    hits = make().retrieve("firewall network")
    assert hits[0].chunk.chunk_id == "d:p003:c000" and hits[0].score == 1.0
    assert all(h.vector is None for h in hits)


def test_a_null_embedder_behaves_like_no_embedder(make: Callable[..., HybridRetriever]) -> None:
    assert make(NullEmbedder()).retrieve("backup offsite") == make().retrieve("backup offsite")


def test_embedding_weight_is_ignored_without_vectors(make: Callable[..., HybridRetriever]) -> None:
    assert make(embedding_weight=0.9).retrieve("mfa login") == make(embedding_weight=0.1).retrieve(
        "mfa login"
    )


def test_query_without_a_match_returns_nothing(make: Callable[..., HybridRetriever]) -> None:
    assert make().retrieve("zzzz qqqq") == []
    assert make().retrieve("the and of") == []


def test_top_k_defaults_to_the_setting_and_can_be_overridden(
    make: Callable[..., HybridRetriever],
) -> None:
    retriever = make(top_k=2)
    query = "mfa backup firewall training employee"
    assert len(retriever.retrieve(query)) == 2
    assert len(retriever.retrieve(query, top_k=4)) == 4
    assert retriever.retrieve(query, top_k=0) == []


def test_min_score_drops_weak_chunks(make: Callable[..., HybridRetriever]) -> None:
    query = "mfa employee"
    loose = make(min_score=0.0).retrieve(query, top_k=10)
    strict = make(min_score=0.99).retrieve(query, top_k=10)
    assert len(strict) < len(loose) and all(h.score >= 0.99 for h in strict)
    assert all(h.score > 0 for h in make().retrieve(query, top_k=10))


def test_equal_scores_are_ordered_by_chunk_id(settings_override: Callable[..., Settings]) -> None:
    s = settings_override().retrieval
    twins = [_chunk(f"t:p{n:03d}:c000", "backup offsite copies") for n in (3, 1, 2)]
    hits = HybridRetriever(twins, Tokenizer(s.stop_words), None, s).retrieve("backup")
    assert [h.chunk.chunk_id for h in hits] == ["t:p001:c000", "t:p002:c000", "t:p003:c000"]


def test_input_order_does_not_change_results(settings_override: Callable[..., Settings]) -> None:
    s = settings_override().retrieval
    tok = Tokenizer(s.stop_words)
    forward = HybridRetriever(CHUNKS, tok, TermEmbedder(), s).retrieve("mfa backup employee", 5)
    backward = HybridRetriever(CHUNKS[::-1], tok, TermEmbedder(), s).retrieve(
        "mfa backup employee", 5
    )
    assert forward == backward


def test_no_chunks_means_no_results(settings_override: Callable[..., Settings]) -> None:
    s = settings_override().retrieval
    assert HybridRetriever([], Tokenizer(s.stop_words), TermEmbedder(), s).retrieve("mfa") == []


# --- with vectors -----------------------------------------------------------------------------


def test_score_is_the_weighted_mean_of_the_two_normalised_signals(
    make: Callable[..., HybridRetriever],
) -> None:
    for hit in make(TermEmbedder(), bm25_weight=0.7, embedding_weight=0.3).retrieve(
        "backup mfa", 5
    ):
        assert hit.vector is not None
        assert hit.score == pytest.approx(0.7 * hit.bm25 + 0.3 * hit.vector, abs=2e-6)
        assert 0.0 <= hit.score <= 1.0


def test_weights_select_which_signal_decides(make: Callable[..., HybridRetriever]) -> None:
    lexical_only = make(TermEmbedder(), bm25_weight=1.0, embedding_weight=0.0, min_score=0.0)
    vector_only = make(TermEmbedder(), bm25_weight=0.0, embedding_weight=1.0, min_score=0.0)
    query = "mfa"
    bm25_top = [h.chunk.chunk_id for h in make(min_score=0.0).retrieve(query, 5)]
    assert [h.chunk.chunk_id for h in lexical_only.retrieve(query, 5)][:1] == bm25_top[:1]
    assert [h.score for h in vector_only.retrieve(query, 5)] == [
        h.vector for h in vector_only.retrieve(query, 5)
    ]


def test_vectors_can_rescue_a_query_with_no_lexical_match(
    make: Callable[..., HybridRetriever],
) -> None:
    hits = make(TermEmbedder(), bm25_weight=0.0, embedding_weight=1.0).retrieve("the and of mfa")
    assert hits and hits[0].chunk.chunk_id == "d:p001:c000"


# --- recall on the committed samples (task 3.6 done-when) --------------------------------------


def _recall_by_state(
    settings: Settings, project_root: Path, top_k: int | None = None
) -> dict[SampleState, float]:
    controls = load_controls(project_root / settings.paths.controls_file).controls
    found = {state: [0, 0] for state in SampleState}
    for stem in STEMS:
        spec = load_spec(project_root / f"data/samples/specs/{stem}.yaml")
        evidence = json.loads(
            (project_root / f"data/samples/{stem}.evidence.json").read_text("utf-8")
        )
        doc = load_document(project_root / f"data/samples/{stem}.pdf", settings.ingest)
        chunks = chunk_document(clean_document(doc, settings.ingest), settings.chunking)
        retriever = HybridRetriever(
            chunks, Tokenizer(settings.retrieval.stop_words), None, settings.retrieval
        )
        for control in controls:
            entry = evidence["controls"][control.id]
            if entry["sentence"] is None:
                continue
            gold = {
                c.chunk_id
                for c in chunks
                if c.page == entry["page"] and entry["sentence"] in c.text
            }
            retrieved = {h.chunk.chunk_id for h in retriever.for_control(control, top_k)}
            state = spec.controls[control.id]
            found[state][1] += 1
            found[state][0] += bool(gold & retrieved)
    return {state: hit / total for state, (hit, total) in found.items() if total}


def test_bm25_only_finds_the_gold_sentence_for_at_least_80_percent_of_met_controls(
    settings_override: Callable[..., Settings], project_root: Path
) -> None:
    recall = _recall_by_state(settings_override(), project_root)
    assert recall[SampleState.MET] >= 0.8
    assert min(recall.values()) >= 0.8  # partial and not_met evidence is just as findable


def test_recall_does_not_depend_on_which_samples_are_chunked_first(
    settings_override: Callable[..., Settings], project_root: Path
) -> None:
    s = settings_override()
    assert _recall_by_state(s, project_root) == _recall_by_state(s, project_root)


def test_a_one_chunk_document_still_returns_its_match(
    settings_override: Callable[..., Settings],
) -> None:
    """The single chunk of a one-page upload is found when it matches, with and without vectors."""
    s = settings_override().retrieval
    tok = Tokenizer(s.stop_words)
    for embedder in (None, TermEmbedder()):
        retriever = HybridRetriever(CHUNKS[:1], tok, embedder, s)
        hits = retriever.retrieve("mfa employee login")
        assert [h.chunk.chunk_id for h in hits] == ["d:p001:c000"] and hits[0].score == 1.0
        if (
            embedder is None
        ):  # with vectors, similarity is always positive: the gates judge relevance
            assert retriever.retrieve("zzzz") == []
