"""Extra edge cases for the reporter and reviewer agents (errors, audit trail, flag hygiene)."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from vendorguard.agents.reporter import FALLBACK_STAGE, ReporterAgent
from vendorguard.agents.reviewer import ReviewerAgent
from vendorguard.config import Settings
from vendorguard.errors import (
    BudgetExceededError,
    LLMError,
    SchemaValidationError,
    VendorGuardError,
)
from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import Control
from vendorguard.models.evidence import Chunk, DraftCitation, ScoredChunk
from vendorguard.models.finding import DraftFinding, DraftStatus
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.models.score import InherentRisk, InherentTier, RiskBand, RiskScore
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.llm.mock import MockLLM
from vendorguard.reporting.facts import build_facts
from vendorguard.reporting.fallback_summary import fallback_summary
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow
from vendorguard.verification.citation_check import CitationChecker

ROOT = Path(__file__).resolve().parents[3]
SCORE = RiskScore(overall=12.5, band=RiskBand.LOW, domain_scores={"IAM": 10.0}, triggered_rules=[])
FACTS = build_facts("Acme", InherentRisk(tier=InherentTier.LOW, reasons=[]), SCORE, [])
CONTROL = Control(
    id="IAM-02", title="Multi-factor authentication", domain="IAM", criticality="critical",
    iso27001=["8.5"], nist_csf=["PR.AA"], requirement="MFA is enforced.",
    met_criteria="MFA is enforced for all workforce access.", keywords=["MFA"],
)  # fmt: skip
SECRET_QUOTE = "Hardware tokens zebra-quartz-77 guard every login."
DRAFT = DraftFinding(
    status=DraftStatus.MET,
    citations=[DraftCitation(chunk_id="d:p001:c000", quote=SECRET_QUOTE)],
    rationale="Tokens.",
)


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, **fields: Any) -> AuditEvent:
        e = AuditEvent(run_id="r", seq=len(self.events), ts=utcnow(), decision=None, **fields)
        self.events.append(e)
        return e


class Scripted:
    provider, model = "ollama", "fake"

    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self.text, self.error = text, error
        self.hints: Mapping[str, Any] | None = None
        self.calls = 0

    def complete_json(
        self, messages: Sequence[ChatMessage], output_model: type[Any], *, purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[Any]:  # fmt: skip
        self.calls += 1
        self.hints = hints
        if self.error:
            raise self.error
        if purpose == "reporter":
            parsed = output_model(summary=self.text)
        else:
            parsed = output_model(citations=[], rationale="n/a")
        return LLMResult(
            parsed=parsed, usage=Usage(tokens_in=1, tokens_out=1), provider="ollama", model="fake"
        )


def _reporter(s: Settings, llm: Any) -> tuple[ReporterAgent, FakeAudit]:
    audit = FakeAudit()
    prompts = PromptLoader(ROOT / "prompts", s.prompts)
    return ReporterAgent(llm, prompts, audit, CostTracker(s.cost), s.reporting), audit


def _reviewer(s: Settings, llm: Any) -> tuple[ReviewerAgent, FakeAudit]:
    audit = FakeAudit()
    prompts = PromptLoader(ROOT / "prompts", s.prompts)
    agent = ReviewerAgent(llm, prompts, audit, CostTracker(s.cost), s.verification, s.decision.rule)
    return agent, audit


def _hits(*texts: str) -> list[ScoredChunk]:
    return [
        ScoredChunk(
            chunk=Chunk(chunk_id=f"d:p{i:03d}:c000", doc_id="d", page=i, text=t,
                        char_start=0, char_end=len(t)),
            score=1.0, bm25=1.0,
        )
        for i, t in enumerate(texts, start=1)
    ]  # fmt: skip


def test_budget_exceeded_propagates_from_the_reporter(settings_override: Any) -> None:
    s: Settings = settings_override()
    agent, audit = _reporter(s, Scripted(error=BudgetExceededError("cap")))
    with pytest.raises(BudgetExceededError):
        agent.summarize(FACTS)
    assert [e.stage for e in audit.events] == ["reporter.failed"]  # no fallback event


def test_schema_validation_error_falls_back(settings_override: Any) -> None:
    s: Settings = settings_override()
    agent, audit = _reporter(s, Scripted(error=SchemaValidationError("bad json")))
    assert agent.summarize(FACTS) == fallback_summary(FACTS)
    assert [e.stage for e in audit.events] == ["reporter.failed", FALLBACK_STAGE]


def test_fallback_event_is_deterministic_and_has_no_tokens(settings_override: Any) -> None:
    s: Settings = settings_override()
    runs = []
    for _ in range(2):
        agent, audit = _reporter(s, Scripted("Score 99.9 for Acme."))
        agent.summarize(FACTS)
        runs.append(audit.events[-1])
    assert runs[0].stage == FALLBACK_STAGE
    assert runs[0].output_hash == runs[1].output_hash
    assert runs[0].input_hash == runs[1].input_hash
    assert runs[0].tokens_in == runs[0].tokens_out == 0 and runs[0].usd == 0.0


def test_unknown_control_id_and_word_limit_trigger_fallback(settings_override: Any) -> None:
    s: Settings = settings_override()
    agent, _ = _reporter(s, Scripted("Gap in ZZZ-99 only."))
    assert agent.summarize(FACTS) == fallback_summary(FACTS)
    long_text = "word " * (s.reporting.summary_max_words + 5)
    agent, _ = _reporter(s, Scripted(long_text))
    assert agent.summarize(FACTS) == fallback_summary(FACTS)


def test_reporter_hints_are_the_facts_and_output_is_stable(settings_override: Any) -> None:
    s: Settings = settings_override()
    llm = Scripted("Acme scores 12.5 (low).")
    agent, _ = _reporter(s, llm)
    first = agent.summarize(FACTS)
    assert dict(llm.hints or {}) == dict(FACTS)
    assert agent.summarize(FACTS) == first


def test_reviewer_failure_writes_one_failed_event_and_reraises(settings_override: Any) -> None:
    s: Settings = settings_override()
    agent, audit = _reviewer(s, Scripted(error=LLMError("down")))
    with pytest.raises(VendorGuardError):
        agent.review(CONTROL, DRAFT, ["x"], _hits("text"))
    assert [e.stage for e in audit.events] == ["reviewer.failed"]
    assert audit.events[0].control_id == "IAM-02"


def test_reviewer_hints_are_sorted_chunks_without_draft_or_flags(settings_override: Any) -> None:
    s: Settings = settings_override()
    llm = Scripted()
    agent, _ = _reviewer(s, llm)
    agent.review(CONTROL, DRAFT, ["quote not found"], list(reversed(_hits("one", "two"))))
    hints = dict(llm.hints or {})
    assert [c["chunk_id"] for c in hints["chunks"]] == ["d:p001:c000", "d:p002:c000"]
    assert hints["max_quote_chars"] == s.verification.max_quote_chars
    assert "quote not found" not in str(hints) and SECRET_QUOTE not in str(hints)


def test_citation_problems_used_as_flags_hold_no_quote_text(settings_override: Any) -> None:
    s: Settings = settings_override()
    evidence = _hits("All staff sign in with MFA.")
    report = CitationChecker(s.verification).check(
        DRAFT.status, DRAFT.citations, [e.chunk for e in evidence]
    )
    assert not report.ok and report.problems
    assert all(SECRET_QUOTE not in p and "zebra" not in p for p in report.problems)
    llm = Scripted()
    agent, audit = _reviewer(s, llm)
    agent.review(CONTROL, DRAFT, report.problems, evidence)
    assert len(audit.events) == 1
    ev = audit.events[0]
    assert "zebra" not in ev.model_dump_json()


def test_reviewer_is_deterministic_on_the_mock(settings_override: Any) -> None:
    s: Settings = settings_override()
    evidence = _hits("All staff sign in with MFA.")
    outs, hashes = [], []
    for _ in range(2):
        agent, audit = _reviewer(s, MockLLM(s.decision.rule))
        outs.append(agent.review(CONTROL, DRAFT, ["x"], evidence))
        hashes.append((audit.events[0].input_hash, audit.events[0].output_hash))
    assert outs[0] == outs[1] and hashes[0] == hashes[1]


def test_reviewer_unicode_evidence_is_kept_verbatim(settings_override: Any) -> None:
    s: Settings = settings_override()
    text = "Alle Mitarbeiter nutzen MFA — überall ✓ 日本語."
    agent, _ = _reviewer(s, Scripted())
    # must render and call once without error
    assert agent.review(CONTROL, DRAFT, [], _hits(text)).status is DraftStatus.NO_EVIDENCE
