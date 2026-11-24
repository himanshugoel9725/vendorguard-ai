"""Table-driven tests for the rule decider and the shared rule logic."""

import pytest

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.control import Control
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.evidence import Chunk, DraftCitation, ScoredChunk
from vendorguard.models.finding import DraftFinding, DraftStatus
from vendorguard.providers.decide.rule import RuleDecider
from vendorguard.verification.rule_logic import triage_verdict, verify_verdict

RULES = RuleDeciderSettings(
    triage_min_keyword_hits=2,
    triage_min_retrieval_score=0.15,
    verify_min_keyword_coverage=0.3,
    unsure_confidence=0.5,
    partial_signal_phrases=["where feasible", "planned"],
    negative_signal_phrases=["does not", "not currently"],
)
KW = ["encryption", "at rest", "aes-256", "keys"]


def _chunk(text: str, cosine: float | None = None) -> ScoredChunk:
    c = Chunk(
        chunk_id="d:p001:c000", doc_id="d", page=1, text=text, char_start=0, char_end=len(text)
    )
    return ScoredChunk(chunk=c, score=1.0, bm25=1.0, bm25_raw=9.0, vector_raw=cosine)


def _draft(status: DraftStatus, *quotes: str) -> DraftFinding:
    return DraftFinding(
        status=status,
        citations=[DraftCitation(chunk_id="d:p001:c000", quote=q) for q in quotes],
        rationale="r",
    )


@pytest.fixture
def control() -> Control:
    return Control.model_construct(id="DAT-02", keywords=KW)


@pytest.mark.parametrize(
    ("text", "raw", "label", "confidence"),
    [
        ("Encryption at rest uses AES-256.", None, DecisionLabel.ADDRESSED, 0.875),
        ("Encryption is used.", None, DecisionLabel.NOT_ADDRESSED, 0.5),  # near miss, never skipped
        ("Nothing relevant here.", None, DecisionLabel.NOT_ADDRESSED, 1.0),
        ("Nothing relevant here.", 0.2, DecisionLabel.ADDRESSED, 0.5),  # embedding similarity floor
    ],
)
def test_triage_table(
    control: Control, text: str, raw: float | None, label: DecisionLabel, confidence: float
) -> None:
    d = RuleDecider(RULES).triage(control, [_chunk(text, raw)])
    assert (d.label, d.confidence, d.provider) == (label, confidence, "rule")


def test_triage_without_evidence_is_not_addressed(control: Control) -> None:
    assert RuleDecider(RULES).triage(control, []).label is DecisionLabel.NOT_ADDRESSED


@pytest.mark.parametrize(
    ("status", "quote", "label"),
    [
        (DraftStatus.MET, "Encryption at rest uses AES-256.", DecisionLabel.SUPPORTED),
        (
            DraftStatus.MET,
            "Encryption at rest uses AES-256 where feasible.",
            DecisionLabel.UNSUPPORTED,
        ),
        (
            DraftStatus.MET,
            "Encryption at rest is planned. Keys do rotate.",
            DecisionLabel.UNSUPPORTED,
        ),
        (DraftStatus.PARTIAL, "Encryption at rest is planned.", DecisionLabel.SUPPORTED),
        (DraftStatus.PARTIAL, "Encryption at rest uses AES-256.", DecisionLabel.UNSUPPORTED),
        (
            DraftStatus.NOT_MET,
            "The vendor does not use encryption at rest.",
            DecisionLabel.SUPPORTED,
        ),
        (DraftStatus.NOT_MET, "Encryption at rest uses AES-256.", DecisionLabel.UNSUPPORTED),
        (DraftStatus.MET, "The weather is nice today.", DecisionLabel.UNSUPPORTED),  # no coverage
    ],
)
def test_verify_table(
    control: Control, status: DraftStatus, quote: str, label: DecisionLabel
) -> None:
    d = RuleDecider(RULES).verify(control, _draft(status, quote), [])
    assert d.label is label and d.confidence == 1.0


def test_verify_reads_the_whole_quote_not_the_first_sentence(control: Control) -> None:
    quote = "Encryption at rest uses AES-256. Keys are not currently rotated."
    assert verify_verdict(DraftStatus.MET, [quote], KW, RULES).label is DecisionLabel.UNSUPPORTED


def test_no_evidence_is_supported_only_without_quotes(control: Control) -> None:
    d = RuleDecider(RULES)
    assert d.verify(control, _draft(DraftStatus.NO_EVIDENCE), []).label is DecisionLabel.SUPPORTED
    assert (
        d.verify(control, _draft(DraftStatus.NO_EVIDENCE, "Encryption at rest."), []).label
        is DecisionLabel.UNSUPPORTED
    )


def test_met_without_quotes_is_unsupported(control: Control) -> None:
    assert (
        RuleDecider(RULES).verify(control, _draft(DraftStatus.MET), []).label
        is DecisionLabel.UNSUPPORTED
    )


def test_deterministic() -> None:
    a = triage_verdict(["Encryption at rest"], KW, 0.0, RULES)
    assert a == triage_verdict(["Encryption at rest"], KW, 0.0, RULES)
