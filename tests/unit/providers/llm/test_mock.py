"""The mock LLM: every purpose gives a valid answer, and the baseline reaches the golden labels."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import LLMError, SchemaValidationError
from vendorguard.eval.golden import load_golden
from vendorguard.eval.specs import load_spec
from vendorguard.ingest.chunker import chunk_document
from vendorguard.ingest.loader import load_document
from vendorguard.ingest.text_cleaner import clean_document
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.finding import DraftFinding, DraftStatus
from vendorguard.models.outputs import AskOutput, JudgeOutput, SummaryOutput
from vendorguard.models.vendor import VendorProfile
from vendorguard.providers.llm.mock import MockLLM
from vendorguard.retrieval.hybrid import HybridRetriever
from vendorguard.retrieval.tokenizer import Tokenizer

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]
KEYWORDS = ["multi-factor authentication", "MFA", "single sign-on"]


@pytest.fixture
def mock(settings_override: Callable[..., Settings]) -> MockLLM:
    return MockLLM(settings_override().decision.rule)


def _map(
    mock: MockLLM, *chunks: tuple[str, str], keywords: list[str] = KEYWORDS, **extra: Any
) -> DraftFinding:
    hints = {
        "keywords": keywords,
        "chunks": [{"chunk_id": c, "text": t} for c, t in chunks],
        **extra,
    }
    return mock.complete_json([], DraftFinding, purpose="mapper", hints=hints).parsed


# --- every purpose gives valid output (task 4.4 done-when) ---------------------------------------


def test_every_purpose_returns_a_valid_model_with_zero_usage(mock: MockLLM) -> None:
    runs = [{"run_id": "run_a", "overall": 20.5, "band": "low", "findings": {"IAM-02": "met"}}]
    intake = {"text": "Security & Trust Overview Acme Reporting period: 2025."}
    triage = {"task": "triage", "keywords": KEYWORDS, "evidence": ["MFA and SSO"]}
    verify = {"task": "verify", "keywords": KEYWORDS, "status": "met", "quotes": []}
    report = {
        "vendor_name": "Acme",
        "overall": 12.5,
        "band": "low",
        "counts": {"met": 25},
        "gaps": [],
    }
    calls: list[tuple[type, str, dict[str, Any]]] = [
        (VendorProfile, "intake", intake),
        (DraftFinding, "mapper", {"keywords": KEYWORDS, "chunks": []}),
        (JudgeOutput, "judge", triage),
        (JudgeOutput, "judge", verify),
        (SummaryOutput, "reporter", report),
        (AskOutput, "ask", {"question": "How is it?", "runs": runs}),
    ]
    for model, purpose, hints in calls:
        result = mock.complete_json([], model, purpose=purpose, hints=hints)
        assert isinstance(result.parsed, model)
        assert (result.provider, result.model, result.cached) == ("mock", "keyword-baseline", False)
        assert (result.usage.tokens_in, result.usage.tokens_out) == (0, 0)


def test_unknown_purpose_and_missing_hints_are_llm_errors(mock: MockLLM) -> None:
    with pytest.raises(LLMError, match="does not know the purpose 'poem'"):
        mock.complete_json([], DraftFinding, purpose="poem")
    for purpose, model in [
        ("intake", VendorProfile),
        ("mapper", DraftFinding),
        ("judge", JudgeOutput),
    ]:
        with pytest.raises(LLMError, match="needs the hint"):
            mock.complete_json([], model, purpose=purpose)
    with pytest.raises(LLMError, match="does not know the task"):
        mock.complete_json([], JudgeOutput, purpose="judge", hints={"task": "x", "keywords": []})


def test_an_answer_that_does_not_fit_the_requested_model_is_a_schema_error(mock: MockLLM) -> None:
    with pytest.raises(SchemaValidationError, match="does not fit JudgeOutput"):
        mock.complete_json([], JudgeOutput, purpose="mapper", hints={"keywords": [], "chunks": []})


def test_the_messages_are_ignored_and_answers_are_deterministic(mock: MockLLM) -> None:
    hints = {
        "keywords": KEYWORDS,
        "chunks": [{"chunk_id": "a:p001:c000", "text": "MFA is enforced."}],
    }
    a = mock.complete_json([], DraftFinding, purpose="mapper", hints=hints)
    b = mock.complete_json([], DraftFinding, purpose="mapper", hints=hints)
    assert a.parsed == b.parsed


# --- mapper --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Multi-factor authentication is mandatory for all staff.", DraftStatus.MET),
        ("MFA is planned for next year.", DraftStatus.PARTIAL),
        ("MFA is not enforced for staff accounts.", DraftStatus.NOT_MET),
    ],
)
def test_mapper_reads_the_status_of_the_first_keyword_sentence(
    mock: MockLLM, text: str, status: DraftStatus
) -> None:
    finding = _map(mock, ("d:p001:c000", f"Intro sentence. {text} Later MFA is fine."))
    assert finding.status is status
    assert [c.quote for c in finding.citations] == [text]
    assert finding.citations[0].chunk_id == "d:p001:c000"
    assert finding.rationale.startswith("Keyword baseline")


def test_mapper_without_a_keyword_sentence_reports_no_evidence(mock: MockLLM) -> None:
    finding = _map(mock, ("d:p001:c000", "Nothing relevant here."))
    assert finding.status is DraftStatus.NO_EVIDENCE and finding.citations == []
    assert _map(mock).status is DraftStatus.NO_EVIDENCE


def test_mapper_scans_chunks_in_document_order_not_the_order_given(mock: MockLLM) -> None:
    late = ("d:p005:c000", "MFA is not enforced.")
    early = ("d:p002:c000", "MFA is enforced for all.")
    finding = _map(mock, late, early)  # retrieval order: late chunk first
    assert finding.status is DraftStatus.MET and finding.citations[0].chunk_id == "d:p002:c000"


def test_the_quote_is_verbatim_and_can_be_cut_to_a_limit(mock: MockLLM) -> None:
    sentence = (
        "MFA is enforced for every employee, contractor and administrator across all systems."
    )
    chunk = ("d:p001:c000", f"Before. {sentence} After.")
    assert _map(mock, chunk).citations[0].quote == sentence
    cut = _map(mock, chunk, max_quote_chars=20).citations[0].quote
    assert sentence.startswith(cut) and len(cut) <= 20 and cut == cut.rstrip()


def test_mapper_matches_whole_words_only(mock: MockLLM) -> None:
    assert (
        _map(mock, ("d:p001:c000", "We keep backups."), keywords=["backup"]).status
        is DraftStatus.NO_EVIDENCE
    )


# --- judge ---------------------------------------------------------------------------------------


def _judge(mock: MockLLM, **hints: Any) -> JudgeOutput:
    return mock.complete_json([], JudgeOutput, purpose="judge", hints=hints).parsed


def test_triage_needs_the_configured_number_of_keyword_hits(
    mock: MockLLM, settings_override: Callable[..., Settings]
) -> None:
    needed = settings_override().decision.rule.triage_min_keyword_hits
    enough = _judge(mock, task="triage", keywords=KEYWORDS, evidence=["MFA with single sign-on."])
    assert enough.label is DecisionLabel.ADDRESSED and 0.5 <= enough.confidence <= 1.0
    one = _judge(mock, task="triage", keywords=KEYWORDS, evidence=["MFA only."])
    expected = DecisionLabel.ADDRESSED if needed <= 1 else DecisionLabel.NOT_ADDRESSED
    assert one.label is expected
    none = _judge(mock, task="triage", keywords=KEYWORDS, evidence=["Nothing."])
    assert (none.label, none.confidence) == (DecisionLabel.NOT_ADDRESSED, 1.0)


@pytest.mark.parametrize(
    ("status", "quotes", "label"),
    [
        ("met", ["MFA and single sign-on are enforced."], DecisionLabel.SUPPORTED),
        ("met", ["MFA and single sign-on are planned."], DecisionLabel.UNSUPPORTED),
        ("partial", ["MFA and single sign-on are planned."], DecisionLabel.SUPPORTED),
        ("not_met", ["MFA and single sign-on are not enforced."], DecisionLabel.SUPPORTED),
        ("not_met", ["MFA and single sign-on are enforced."], DecisionLabel.UNSUPPORTED),
        ("met", [], DecisionLabel.UNSUPPORTED),
        ("met", ["Unrelated sentence."], DecisionLabel.UNSUPPORTED),
        ("no_evidence", [], DecisionLabel.SUPPORTED),
        ("no_evidence", ["MFA and single sign-on are enforced."], DecisionLabel.UNSUPPORTED),
    ],
)
def test_verify_checks_status_against_the_quotes(
    mock: MockLLM, status: str, quotes: list[str], label: DecisionLabel
) -> None:
    out = _judge(mock, task="verify", keywords=KEYWORDS, status=status, quotes=quotes)
    assert (
        out.label is label and out.confidence == 1.0 and out.reason.startswith("Keyword baseline")
    )


# --- reporter and ask ----------------------------------------------------------------------------


def _summary(mock: MockLLM, **overrides: Any) -> str:
    hints: dict[str, Any] = {"vendor_name": "Acme", "overall": 41.25, "band": "medium",
                             "counts": {"met": 20, "partial": 3, "not_met": 1, "no_evidence": 1},
                             "gaps": ["PEO-02", "IAM-04"], **overrides}  # fmt: skip
    return mock.complete_json([], SummaryOutput, purpose="reporter", hints=hints).parsed.summary


def test_the_summary_uses_only_given_numbers_and_ids(mock: MockLLM) -> None:
    text = _summary(mock)
    assert (
        "41.25" in text and "(medium)" in text and "Of 25 controls, 20 are met, 3 partially" in text
    )
    assert "IAM-04, PEO-02" in text  # sorted
    assert "no open gaps" in _summary(mock, gaps=[])
    assert len(text.split()) < 150


def test_ask_answers_about_named_controls_changes_and_the_latest_run(mock: MockLLM) -> None:
    old = {
        "run_id": "run_old",
        "overall": 30.0,
        "band": "medium",
        "findings": {"IAM-04": "partial", "OPS-02": "met", "GOV-01": "met"},
    }
    new = {
        "run_id": "run_new",
        "overall": 25.5,
        "band": "low",
        "findings": {"IAM-04": "met", "OPS-02": "partial", "GOV-01": "met"},
    }

    def ask(question: str, runs: list[dict[str, Any]]) -> AskOutput:
        return mock.complete_json(
            [], AskOutput, purpose="ask", hints={"question": question, "runs": runs}
        ).parsed

    changed = ask("What changed since last year?", [new, old])
    assert "from 30 to 25.5" in changed.text and "New gaps: OPS-02" in changed.text
    assert "Resolved gaps: IAM-04" in changed.text
    assert changed.cited_run_ids == ["run_new", "run_old"] and changed.cited_control_ids == [
        "OPS-02",
        "IAM-04",
    ]
    named = ask("Is OPS-02 and ZZZ-99 fine?", [new, old])  # unknown IDs are ignored
    assert named.text == "OPS-02 is partial in run run_new." and named.cited_control_ids == [
        "OPS-02"
    ]
    general = ask("How are they doing?", [new])
    assert general.text == "Latest run run_new: overall score 25.5 (low). Gaps: OPS-02."
    assert ask("anything", []).cited_run_ids == []
    assert "Gaps: none" in ask("anything", [old | {"findings": {"A-01": "met"}}]).text


# --- intake and the golden labels on the committed samples ---------------------------------------


@pytest.fixture
def prepared(
    settings_override: Callable[..., Settings], project_root: Path
) -> Callable[[str], tuple[Any, ...]]:
    s = settings_override()

    def load(stem: str) -> tuple[Any, ...]:
        doc = clean_document(
            load_document(project_root / f"data/samples/{stem}.pdf", s.ingest), s.ingest
        )
        return s, chunk_document(doc, s.chunking)

    return load


@pytest.mark.parametrize("stem", STEMS)
def test_intake_recovers_every_vendor_fact_of_the_spec(
    mock: MockLLM, prepared: Callable[[str], tuple[Any, ...]], project_root: Path, stem: str
) -> None:
    s, chunks = prepared(stem)
    spec = load_spec(project_root / f"data/samples/specs/{stem}.yaml")
    text = " ".join(c.text for c in chunks[: s.intake.max_chunks])
    profile = mock.complete_json([], VendorProfile, purpose="intake", hints={"text": text}).parsed
    assert profile.vendor_name == spec.vendor_name
    assert (profile.services, profile.hosting) == (spec.services, spec.hosting)
    assert (profile.certifications, profile.subprocessors) == (
        spec.certifications,
        spec.subprocessors,
    )
    assert profile.report_period == spec.report_period
    assert [d.value for d in profile.data_categories] == [d.value for d in spec.data_categories]


@pytest.mark.parametrize("stem", STEMS)
def test_the_keyword_baseline_reaches_the_golden_labels(
    mock: MockLLM, prepared: Callable[[str], tuple[Any, ...]], project_root: Path, stem: str
) -> None:
    """Retrieval plus the mock mapper: at least 85 % (task 5.3); the samples give 100 %."""
    s, chunks = prepared(stem)
    controls = load_controls(project_root / s.paths.controls_file).controls
    gold = load_golden(project_root / f"data/golden/{stem}.json")
    retriever = HybridRetriever(chunks, Tokenizer(s.retrieval.stop_words), None, s.retrieval)
    right = 0
    for control in controls:
        hits = retriever.for_control(control)
        hints = {
            "keywords": control.keywords,
            "chunks": [{"chunk_id": h.chunk.chunk_id, "text": h.chunk.text} for h in hits],
            "max_quote_chars": s.verification.max_quote_chars,
        }
        got = mock.complete_json([], DraftFinding, purpose="mapper", hints=hints).parsed
        right += got.status is gold.controls[control.id]
        for citation in got.citations:  # every quote is verbatim text of the cited chunk
            assert citation.quote in next(
                h.chunk.text for h in hits if h.chunk.chunk_id == citation.chunk_id
            )
    assert right / len(controls) >= 0.85
    assert right == len(controls)


def test_the_mock_needs_no_network(mock: MockLLM) -> None:
    import socket

    real = socket.socket
    socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))  # type: ignore[assignment]
    try:
        mock.complete_json(
            [], DraftFinding, purpose="mapper", hints={"keywords": ["x"], "chunks": []}
        )
    finally:
        socket.socket = real  # type: ignore[misc]
    assert json.dumps({"ok": True})
