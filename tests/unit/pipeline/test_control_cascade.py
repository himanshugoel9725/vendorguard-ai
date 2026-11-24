"""The per-control cascade, with stub decider/agents and a recording audit sink."""

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.errors import (
    BudgetExceededError,
    CacheMissError,
    DeciderError,
    LLMError,
    SchemaValidationError,
)
from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import Control
from vendorguard.models.decision import Decision, DecisionLabel, Gate
from vendorguard.models.evidence import Chunk, DraftCitation, ScoredChunk
from vendorguard.models.finding import ControlFinding, ControlStatus, DraftFinding, DraftStatus
from vendorguard.pipeline.context import RunContext
from vendorguard.pipeline.control_cascade import (
    HUMAN_PREFIX,
    NO_EVIDENCE_RATIONALE,
    run_cascade,
)
from vendorguard.pipeline.retrieval_plan import ControlEvidence
from vendorguard.utils.timeutil import utcnow
from vendorguard.verification.citation_check import CitationChecker

Make = Callable[..., Settings]

CONTROL = Control(
    id="IAM-02", title="MFA", domain="IAM", criticality="critical", iso27001=["8.5"],
    nist_csf=["PR.AA"], requirement="MFA is enforced.", met_criteria="MFA for all access.",
    keywords=["MFA"],
)  # fmt: skip
TEXT = "Multi-factor authentication is enforced for every administrator and every employee."
WIDE_TEXT = "Backups are encrypted and restored every quarter by the infrastructure team."
BAD_QUOTE = "ZEBRA-QUOTE that appears nowhere in any chunk"


def _chunk(n: int, text: str) -> ScoredChunk:
    c = Chunk(
        chunk_id=f"d:p001:c{n:03d}", doc_id="d", page=1, text=text, char_start=0, char_end=len(text)
    )
    return ScoredChunk(chunk=c, score=1.0, bm25=1.0)


TOP = [_chunk(0, TEXT), _chunk(1, "Passwords are rotated.")]
WIDE_ONLY = _chunk(5, WIDE_TEXT)
EV = ControlEvidence(top=TOP, wide=[*TOP, WIDE_ONLY])


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, **fields: Any) -> AuditEvent:
        e = AuditEvent(run_id="r", seq=len(self.events), ts=utcnow(), **fields)
        self.events.append(e)
        return e

    def stages(self) -> list[str]:
        return [e.stage for e in self.events]


def _dec(label: DecisionLabel, conf: float, reason: str | None = None) -> Decision:
    return Decision(label=label, confidence=conf, provider="stub", reason=reason)


class StubDecider:
    name = "stub"

    def __init__(
        self,
        triage: Decision | Exception | None = None,
        verify: Sequence[Decision | Exception] = (),
    ) -> None:
        self._triage = triage or _dec(DecisionLabel.ADDRESSED, 0.9)
        self._verify = list(verify) or [_dec(DecisionLabel.SUPPORTED, 1.0)]
        self.triage_calls = 0
        self.verify_calls: list[tuple[DraftFinding, list[str]]] = []

    def triage(self, control: Control, evidence: Sequence[ScoredChunk]) -> Decision:
        self.triage_calls += 1
        if isinstance(self._triage, Exception):
            raise self._triage
        return self._triage

    def verify(
        self, control: Control, draft: DraftFinding, evidence: Sequence[ScoredChunk]
    ) -> Decision:
        self.verify_calls.append((draft, [e.chunk.chunk_id for e in evidence]))
        i = min(len(self.verify_calls) - 1, len(self._verify) - 1)
        out = self._verify[i]
        if isinstance(out, Exception):
            raise out
        return out


class StubMapper:
    def __init__(self, draft: DraftFinding | Exception) -> None:
        self.draft = draft
        self.seen: list[list[ScoredChunk]] = []

    def map(self, control: Control, evidence: Sequence[ScoredChunk]) -> DraftFinding:
        self.seen.append(list(evidence))
        if isinstance(self.draft, Exception):
            raise self.draft
        return self.draft


class StubReviewer:
    def __init__(self, draft: DraftFinding | Exception) -> None:
        self.draft = draft
        self.calls: list[tuple[list[str], list[ScoredChunk]]] = []

    def review(
        self,
        control: Control,
        draft: DraftFinding,
        flags: Sequence[str],
        evidence: Sequence[ScoredChunk],
    ) -> DraftFinding:
        self.calls.append((list(flags), list(evidence)))
        if isinstance(self.draft, Exception):
            raise self.draft
        return self.draft


def _draft(quote: str = "Multi-factor authentication is enforced", chunk: int = 0,
           status: DraftStatus = DraftStatus.MET) -> DraftFinding:  # fmt: skip
    return DraftFinding(
        status=status,
        citations=[DraftCitation(chunk_id=f"d:p001:c{chunk:03d}", quote=quote)],
        rationale="MFA is on.",
    )


def _ctx(
    s: Settings, tmp_path: Path, decider: StubDecider, mapper: StubMapper, reviewer: StubReviewer
) -> tuple[RunContext, FakeAudit]:
    audit = FakeAudit()
    ctx = RunContext(
        settings=s, run_id="r", run_dir=tmp_path, audit=audit, decider=decider,
        embedder=None, cost=None, intake=None, mapper=mapper, reviewer=reviewer,  # type: ignore[arg-type]
        reporter=None, citation=CitationChecker(s.verification),  # type: ignore[arg-type]
        abort=threading.Event(),
    )  # fmt: skip
    return ctx, audit


@pytest.fixture
def s(settings_override: Make) -> Settings:
    return settings_override()


def _run(
    s: Settings,
    tmp_path: Path,
    *,
    decider: StubDecider | None = None,
    mapper: StubMapper | None = None,
    reviewer: StubReviewer | None = None,
    ev: ControlEvidence = EV,
) -> tuple[ControlFinding, FakeAudit, StubDecider, StubMapper, StubReviewer]:
    d = decider or StubDecider()
    m = mapper or StubMapper(_draft())
    r = reviewer or StubReviewer(_draft())
    ctx, audit = _ctx(s, tmp_path, d, m, r)
    return run_cascade(ctx, CONTROL, ev), audit, d, m, r


def _check_audit_invariants(f: ControlFinding, audit: FakeAudit) -> None:
    gates = [e for e in audit.events if e.stage.startswith("gate.")]
    assert len(gates) == len(f.trace)
    assert audit.stages().count("cascade.finding") == 1
    assert audit.stages()[-1] == "cascade.finding"
    assert all(e.control_id == CONTROL.id for e in audit.events)


# --- triage ---------------------------------------------------------------------------------


def test_confident_not_addressed_skips_the_mapper(s: Settings, tmp_path: Path) -> None:
    d = StubDecider(triage=_dec(DecisionLabel.NOT_ADDRESSED, s.decision.triage_threshold))
    f, audit, _, m, r = _run(s, tmp_path, decider=d)
    assert f.status is ControlStatus.NO_EVIDENCE and f.rationale == NO_EVIDENCE_RATIONALE
    assert m.seen == [] and r.calls == [] and d.verify_calls == []
    assert [t.gate for t in f.trace] == [Gate.TRIAGE] and f.citations == []
    assert audit.stages() == ["gate.triage", "cascade.finding"]
    _check_audit_invariants(f, audit)


def test_near_miss_still_maps(s: Settings, tmp_path: Path) -> None:
    low = s.decision.triage_threshold - 0.1
    f, audit, _, m, _ = _run(
        s, tmp_path, decider=StubDecider(triage=_dec(DecisionLabel.NOT_ADDRESSED, low))
    )
    assert len(m.seen) == 1 and f.status is ControlStatus.MET
    assert [t.gate for t in f.trace] == [Gate.TRIAGE, Gate.CITATION, Gate.VERIFY]
    _check_audit_invariants(f, audit)


def test_confidence_half_is_a_near_miss(s: Settings, tmp_path: Path) -> None:
    assert s.decision.triage_threshold > 0.5
    f, *_ = _run(s, tmp_path, decider=StubDecider(triage=_dec(DecisionLabel.NOT_ADDRESSED, 0.5)))
    assert f.status is ControlStatus.MET


def test_addressed_with_high_confidence_maps(s: Settings, tmp_path: Path) -> None:
    f, _, _, m, _ = _run(s, tmp_path)
    assert len(m.seen) == 1 and f.status is ControlStatus.MET and f.review_rounds == 0


def test_triage_disabled_has_no_triage_trace(settings_override: Make, tmp_path: Path) -> None:
    s = settings_override(pipeline={"triage_enabled": False})
    d = StubDecider(triage=_dec(DecisionLabel.NOT_ADDRESSED, 1.0))
    f, audit, _, m, _ = _run(s, tmp_path, decider=d)
    assert d.triage_calls == 0 and len(m.seen) == 1
    assert all(t.gate is not Gate.TRIAGE for t in f.trace)
    assert "gate.triage" not in audit.stages()
    _check_audit_invariants(f, audit)


# --- map, citation, verify ------------------------------------------------------------------


def test_happy_path_trace_and_evidence_split(s: Settings, tmp_path: Path) -> None:
    f, audit, d, m, r = _run(s, tmp_path)
    assert m.seen == [EV.top] and r.calls == []
    assert d.verify_calls[0][1] == [h.chunk.chunk_id for h in EV.top]
    assert f.citations[0].valid is True and f.citations[0].doc_id == "d"
    assert f.rationale == "MFA is on."
    _check_audit_invariants(f, audit)


def test_verify_below_threshold_triggers_review_then_accepts(s: Settings, tmp_path: Path) -> None:
    low = _dec(DecisionLabel.SUPPORTED, s.decision.verify_threshold - 0.01, "weak support")
    d = StubDecider(verify=[low, _dec(DecisionLabel.SUPPORTED, 1.0)])
    revised = _draft(WIDE_TEXT[:40], chunk=5, status=DraftStatus.PARTIAL)
    f, audit, _, m, r = _run(s, tmp_path, decider=d, reviewer=StubReviewer(revised))
    assert r.calls == [(["verify gate did not support status met: weak support"], EV.wide)]
    assert m.seen == [EV.top]
    review = [t for t in f.trace if t.gate is Gate.REVIEW]
    assert len(review) == 1 and review[0].round == 1
    assert f.status is ControlStatus.PARTIAL and f.review_rounds == 1
    # round 1 is checked and verified against the WIDE evidence
    assert d.verify_calls[1][1] == [h.chunk.chunk_id for h in EV.wide]
    assert [(t.gate, t.round) for t in f.trace] == [
        (Gate.TRIAGE, 0), (Gate.CITATION, 0), (Gate.VERIFY, 0),
        (Gate.REVIEW, 1), (Gate.CITATION, 1), (Gate.VERIFY, 1),
    ]  # fmt: skip
    _check_audit_invariants(f, audit)


def test_unsupported_verify_without_reason_gets_a_default_flag(s: Settings, tmp_path: Path) -> None:
    d = StubDecider(
        verify=[_dec(DecisionLabel.UNSUPPORTED, 1.0), _dec(DecisionLabel.SUPPORTED, 1.0)]
    )
    _, _, _, _, r = _run(s, tmp_path, decider=d)
    assert len(r.calls) == 1 and r.calls[0][0] and all(r.calls[0][0])


def test_still_unsupported_after_the_last_round_needs_human_review(
    s: Settings, tmp_path: Path
) -> None:
    d = StubDecider(verify=[_dec(DecisionLabel.UNSUPPORTED, 1.0, "nope")])
    f, audit, *_ = _run(s, tmp_path, decider=d)
    assert f.status is ControlStatus.NEEDS_HUMAN_REVIEW
    assert f.rationale == HUMAN_PREFIX + "verify gate did not support status met: nope"
    assert f.review_rounds == s.pipeline.max_review_rounds
    _check_audit_invariants(f, audit)


def test_bad_citation_goes_to_review_then_needs_human_review(s: Settings, tmp_path: Path) -> None:
    bad = _draft(BAD_QUOTE)
    f, audit, d, _, r = _run(s, tmp_path, mapper=StubMapper(bad), reviewer=StubReviewer(bad))
    assert f.status is ControlStatus.NEEDS_HUMAN_REVIEW and f.review_rounds == 1
    assert d.verify_calls == [] and len(r.calls) == 1
    assert [(t.gate, t.round) for t in f.trace][1:] == [
        (Gate.CITATION, 0), (Gate.REVIEW, 1), (Gate.CITATION, 1)
    ]  # fmt: skip
    assert f.citations == []
    _check_audit_invariants(f, audit)


def test_no_quote_text_in_rationale_or_audit(s: Settings, tmp_path: Path) -> None:
    bad = _draft(BAD_QUOTE)
    f, audit, *_ = _run(s, tmp_path, mapper=StubMapper(bad), reviewer=StubReviewer(bad))
    blob = f.model_dump_json() + "".join(e.model_dump_json() for e in audit.events)
    assert "ZEBRA" not in blob and BAD_QUOTE not in blob


def test_reviewer_flags_hold_no_quote_text(s: Settings, tmp_path: Path) -> None:
    _, _, _, _, r = _run(
        s, tmp_path, mapper=StubMapper(_draft(BAD_QUOTE)), reviewer=StubReviewer(_draft(BAD_QUOTE))
    )
    assert r.calls[0][0] and all("ZEBRA" not in f for f in r.calls[0][0])


def test_max_review_rounds_zero_goes_straight_to_human(
    settings_override: Make, tmp_path: Path
) -> None:
    s = settings_override(pipeline={"max_review_rounds": 0})
    f, audit, _, _, r = _run(s, tmp_path, mapper=StubMapper(_draft(BAD_QUOTE)))
    assert r.calls == [] and f.review_rounds == 0
    assert f.status is ControlStatus.NEEDS_HUMAN_REVIEW
    assert [t.gate for t in f.trace] == [Gate.TRIAGE, Gate.CITATION]
    _check_audit_invariants(f, audit)


def test_max_review_rounds_zero_low_verify_goes_to_human(
    settings_override: Make, tmp_path: Path
) -> None:
    s = settings_override(pipeline={"max_review_rounds": 0})
    d = StubDecider(verify=[_dec(DecisionLabel.UNSUPPORTED, 1.0, "no")])
    f, _, _, _, r = _run(s, tmp_path, decider=d)
    assert r.calls == [] and f.status is ControlStatus.NEEDS_HUMAN_REVIEW


def test_two_review_rounds_are_looped_and_counted(settings_override: Make, tmp_path: Path) -> None:
    s = settings_override(pipeline={"max_review_rounds": 2})
    bad = _draft(BAD_QUOTE)
    f, audit, _, _, r = _run(s, tmp_path, mapper=StubMapper(bad), reviewer=StubReviewer(bad))
    assert len(r.calls) == 2 and f.review_rounds == 2
    _check_audit_invariants(f, audit)


def test_the_reviewer_may_cite_a_chunk_only_in_wide(s: Settings, tmp_path: Path) -> None:
    f, _, _, _, _ = _run(
        s, tmp_path, mapper=StubMapper(_draft(WIDE_TEXT[:40], chunk=5)),
        reviewer=StubReviewer(_draft(WIDE_TEXT[:40], chunk=5)),
    )  # fmt: skip
    # the mapper sees only top: a wide-only chunk id is unknown in round 0, the review fixes it
    assert f.status is ControlStatus.MET and f.review_rounds == 1


def test_fuzzy_citation_is_verified_with_the_source_text(s: Settings, tmp_path: Path) -> None:
    model_quote = "Multi-factor authentication is enforced for every administrator and employee"
    d = StubDecider()
    f, _, _, _, r = _run(s, tmp_path, decider=d, mapper=StubMapper(_draft(model_quote)))
    assert r.calls == [] and f.status is ControlStatus.MET
    verified = d.verify_calls[0][0].citations[0].quote
    assert verified != model_quote and "every employee" in verified
    assert f.citations[0].quote == verified and f.citations[0].similarity is not None
    assert f.citations[0].similarity < 1.0


def test_no_evidence_draft_needs_no_citation(s: Settings, tmp_path: Path) -> None:
    draft = DraftFinding(status=DraftStatus.NO_EVIDENCE, citations=[], rationale="nothing")
    f, *_ = _run(s, tmp_path, mapper=StubMapper(draft))
    assert f.status is ControlStatus.NO_EVIDENCE and f.citations == []


# --- errors ---------------------------------------------------------------------------------

RECOVERABLE = [LLMError("x"), SchemaValidationError("x"), DeciderError("x")]


@pytest.mark.parametrize("exc", RECOVERABLE, ids=lambda e: type(e).__name__)
def test_mapper_failure_becomes_human_review_keeping_the_trace(
    s: Settings, tmp_path: Path, exc: Exception
) -> None:
    f, audit, *_ = _run(s, tmp_path, mapper=StubMapper(exc))
    assert f.status is ControlStatus.NEEDS_HUMAN_REVIEW
    assert f.rationale == f"{HUMAN_PREFIX}automatic review failed ({type(exc).__name__})"
    assert [t.gate for t in f.trace] == [Gate.TRIAGE]
    _check_audit_invariants(f, audit)


@pytest.mark.parametrize("exc", RECOVERABLE, ids=lambda e: type(e).__name__)
def test_reviewer_failure_keeps_the_trace_so_far(
    s: Settings, tmp_path: Path, exc: Exception
) -> None:
    f, audit, *_ = _run(
        s, tmp_path, mapper=StubMapper(_draft(BAD_QUOTE)), reviewer=StubReviewer(exc)
    )
    assert f.status is ControlStatus.NEEDS_HUMAN_REVIEW and "failed" in f.rationale
    assert [t.gate for t in f.trace] == [Gate.TRIAGE, Gate.CITATION]
    assert f.review_rounds == 0
    _check_audit_invariants(f, audit)


@pytest.mark.parametrize("exc", RECOVERABLE, ids=lambda e: type(e).__name__)
def test_decider_triage_failure(s: Settings, tmp_path: Path, exc: Exception) -> None:
    f, audit, _, m, _ = _run(s, tmp_path, decider=StubDecider(triage=exc))
    assert f.status is ControlStatus.NEEDS_HUMAN_REVIEW and f.trace == [] and m.seen == []
    _check_audit_invariants(f, audit)


@pytest.mark.parametrize("exc", RECOVERABLE, ids=lambda e: type(e).__name__)
def test_decider_verify_failure(s: Settings, tmp_path: Path, exc: Exception) -> None:
    f, audit, *_ = _run(s, tmp_path, decider=StubDecider(verify=[exc]))
    assert f.status is ControlStatus.NEEDS_HUMAN_REVIEW
    assert [t.gate for t in f.trace] == [Gate.TRIAGE, Gate.CITATION]
    assert f.citations == []  # the failure path never trusts unverified quotes
    _check_audit_invariants(f, audit)


@pytest.mark.parametrize("exc", [BudgetExceededError("b"), CacheMissError("c")])
@pytest.mark.parametrize("where", ["mapper", "reviewer", "triage", "verify"])
def test_budget_and_cache_miss_propagate(
    s: Settings, tmp_path: Path, exc: Exception, where: str
) -> None:
    kw: dict[str, Any] = {}
    if where == "mapper":
        kw["mapper"] = StubMapper(exc)
    elif where == "reviewer":
        kw.update(mapper=StubMapper(_draft(BAD_QUOTE)), reviewer=StubReviewer(exc))
    elif where == "triage":
        kw["decider"] = StubDecider(triage=exc)
    else:
        kw["decider"] = StubDecider(verify=[exc])
    with pytest.raises(type(exc)):
        _run(s, tmp_path, **kw)


def test_a_propagating_error_writes_no_closing_event(s: Settings, tmp_path: Path) -> None:
    ctx, audit = _ctx(
        s, tmp_path, StubDecider(), StubMapper(BudgetExceededError("b")), StubReviewer(_draft())
    )
    with pytest.raises(BudgetExceededError):
        run_cascade(ctx, CONTROL, EV)
    assert "cascade.finding" not in audit.stages()


# --- determinism ----------------------------------------------------------------------------


def test_same_input_same_finding_and_audit_hashes(s: Settings, tmp_path: Path) -> None:
    a = _run(s, tmp_path)
    b = _run(s, tmp_path)
    assert a[0].model_dump() == b[0].model_dump()
    hashes = lambda au: [(e.stage, e.input_hash, e.output_hash) for e in au.events]  # noqa: E731
    assert hashes(a[1]) == hashes(b[1])


# --- relocated citations and the human-review rationale -------------------------------------


def test_a_relocated_citation_is_verified_and_keeps_the_corrected_chunk(
    s: Settings, tmp_path: Path
) -> None:
    wrong = _draft("Multi-factor authentication is enforced", chunk=1)  # quote is in chunk 0
    d = StubDecider()
    f, audit, _, _, r = _run(s, tmp_path, decider=d, mapper=StubMapper(wrong))
    assert r.calls == [] and f.status is ControlStatus.MET and f.review_rounds == 0
    assert [(c.chunk_id, c.relocated, c.valid) for c in f.citations] == [
        ("d:p001:c000", True, True)
    ]
    verified = d.verify_calls[0][0]
    assert [c.chunk_id for c in verified.citations] == ["d:p001:c000"]
    _check_audit_invariants(f, audit)


def test_human_review_rationale_names_the_gate_and_status_without_quote_text(
    s: Settings, tmp_path: Path
) -> None:
    d = StubDecider(verify=[_dec(DecisionLabel.UNSUPPORTED, 1.0, "does not say so")])
    f, audit, *_ = _run(s, tmp_path, decider=d)
    assert f.rationale.startswith(HUMAN_PREFIX)
    assert "verify gate did not support status met" in f.rationale
    assert "Multi-factor authentication is enforced" not in f.rationale

    bad = _draft(BAD_QUOTE)
    f2, _, *_ = _run(s, tmp_path, mapper=StubMapper(bad), reviewer=StubReviewer(bad))
    assert f2.rationale.startswith(HUMAN_PREFIX + "citation gate: ")
    assert "ZEBRA" not in f2.rationale
