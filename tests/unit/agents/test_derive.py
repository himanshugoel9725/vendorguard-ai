"""derive_finding (ADR-017): the model picks quotes, Python derives the status."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from vendorguard.agents.derive import NOT_ABOUT_CONTROL, derive_finding
from vendorguard.agents.mapper import MapperAgent
from vendorguard.agents.reviewer import ReviewerAgent
from vendorguard.config import Settings
from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import Control
from vendorguard.models.evidence import Chunk, DraftCitation, ScoredChunk
from vendorguard.models.finding import (
    MAX_CITATIONS,
    MAX_RATIONALE_WORDS,
    DraftFinding,
    DraftStatus,
    ExtractedEvidence,
)
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow

ROOT = Path(__file__).resolve().parents[3]
CONTROL = Control(
    id="IAM-02", title="Multi-factor authentication", domain="IAM", criticality="critical",
    iso27001=["8.5"], nist_csf=["PR.AA"], requirement="MFA is enforced.",
    met_criteria="MFA is enforced for all workforce access.", keywords=["MFA", "2FA"],
)  # fmt: skip


def _ev(*quotes: str, rationale: str = "Model rationale.") -> ExtractedEvidence:
    return ExtractedEvidence(
        citations=[
            DraftCitation(chunk_id=f"d:p{i:03d}:c000", quote=q) for i, q in enumerate(quotes, 1)
        ],
        rationale=rationale,
    )


@pytest.fixture
def s(settings_override: Callable[..., Settings]) -> Settings:
    return settings_override()


def test_no_citations_is_no_evidence_and_keeps_the_rationale(s: Settings) -> None:
    out = derive_finding(CONTROL, _ev(rationale="Nothing relevant was found."), s.decision.rule)
    assert out == DraftFinding(
        status=DraftStatus.NO_EVIDENCE, citations=[], rationale="Nothing relevant was found."
    )


def test_quotes_without_a_control_keyword_are_no_evidence_with_no_citations(s: Settings) -> None:
    out = derive_finding(CONTROL, _ev("Backups run nightly.", "Passwords rotate."), s.decision.rule)
    assert out.status is DraftStatus.NO_EVIDENCE
    assert out.citations == [] and out.rationale == NOT_ABOUT_CONTROL


def test_keyword_match_is_whole_word(s: Settings) -> None:
    out = derive_finding(CONTROL, _ev("The MFAs are many."), s.decision.rule)
    assert out.status is DraftStatus.NO_EVIDENCE


def test_negative_phrase_gives_not_met(s: Settings) -> None:
    out = derive_finding(CONTROL, _ev("MFA is not enforced for staff."), s.decision.rule)
    assert out.status is DraftStatus.NOT_MET


def test_negative_phrase_in_any_quote_beats_partial_in_another(s: Settings) -> None:
    partial = f"MFA is {s.decision.rule.partial_signal_phrases[0]} for admins."
    negative = f"MFA {s.decision.rule.negative_signal_phrases[0]} apply to contractors."
    for quotes in ((partial, negative), (negative, partial)):
        out = derive_finding(CONTROL, _ev(*quotes), s.decision.rule)
        assert out.status is DraftStatus.NOT_MET


def test_partial_phrase_gives_partial(s: Settings) -> None:
    text = f"MFA is enforced {s.decision.rule.partial_signal_phrases[0]}."
    assert derive_finding(CONTROL, _ev(text), s.decision.rule).status is DraftStatus.PARTIAL


def test_no_signal_gives_met(s: Settings) -> None:
    out = derive_finding(CONTROL, _ev("All staff sign in with MFA."), s.decision.rule)
    assert out.status is DraftStatus.MET


def test_the_whole_joined_quote_is_read_not_only_the_first(s: Settings) -> None:
    neg = s.decision.rule.negative_signal_phrases[0]
    out = derive_finding(
        CONTROL, _ev("MFA is available.", f"Contractors {neg} use it."), s.decision.rule
    )
    assert out.status is DraftStatus.NOT_MET
    # a keyword in only the second quote is enough to be about the control
    out = derive_finding(
        CONTROL, _ev("Staff are trained.", "2FA protects logins."), s.decision.rule
    )
    assert out.status is DraftStatus.MET and len(out.citations) == 2


def test_output_citations_and_rationale_are_the_extracted_ones(s: Settings) -> None:
    ext = _ev("All staff sign in with MFA.", "2FA is on.", rationale="Both mention it.")
    out = derive_finding(CONTROL, ext, s.decision.rule)
    assert out.citations == ext.citations and out.rationale == "Both mention it."


def test_unicode_quotes(s: Settings) -> None:
    out = derive_finding(
        CONTROL, _ev("Alle Mitarbeiter nutzen MFA — überall ✓ 日本語."), s.decision.rule
    )
    assert out.status is DraftStatus.MET and "日本語" in out.citations[0].quote


def test_is_deterministic(s: Settings) -> None:
    ext = _ev("MFA is not enforced.")
    assert derive_finding(CONTROL, ext, s.decision.rule) == derive_finding(
        CONTROL, ext, s.decision.rule
    )


# --- the agents return the derived status ------------------------------------------------------


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, **fields: Any) -> AuditEvent:
        e = AuditEvent(run_id="r", seq=len(self.events), ts=utcnow(), decision=None, **fields)
        self.events.append(e)
        return e


class Fixed:
    provider, model = "ollama", "fake"

    def __init__(self, parsed: ExtractedEvidence) -> None:
        self.parsed = parsed
        self.schemas: list[type[Any]] = []

    def complete_json(
        self, messages: Sequence[ChatMessage], output_model: type[Any], *, purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[Any]:  # fmt: skip
        self.schemas.append(output_model)
        return LLMResult(
            parsed=self.parsed,
            usage=Usage(tokens_in=1, tokens_out=1),
            provider="ollama",
            model="fake",
        )


def _hits(*texts: str) -> list[ScoredChunk]:
    return [
        ScoredChunk(
            chunk=Chunk(chunk_id=f"d:p{i:03d}:c000", doc_id="d", page=i, text=t,
                        char_start=0, char_end=len(t)),
            score=1.0, bm25=1.0,
        )
        for i, t in enumerate(texts, start=1)
    ]  # fmt: skip


def test_mapper_and_reviewer_return_the_derived_status(s: Settings) -> None:
    ext = _ev("MFA is not enforced for staff.")
    prompts = PromptLoader(ROOT / "prompts", s.prompts)
    llm = Fixed(ext)
    mapper = MapperAgent(
        llm, prompts, FakeAudit(), CostTracker(s.cost), s.verification, s.decision.rule
    )
    reviewer = ReviewerAgent(
        llm, prompts, FakeAudit(), CostTracker(s.cost), s.verification, s.decision.rule
    )
    draft = mapper.map(CONTROL, _hits("x"))
    assert draft.status is DraftStatus.NOT_MET and draft.citations == ext.citations
    assert reviewer.review(CONTROL, draft, ["flag"], _hits("x")).status is DraftStatus.NOT_MET
    assert llm.schemas == [ExtractedEvidence, ExtractedEvidence]


# --- the shipped prompts ---------------------------------------------------------------------


def _vars(s: Settings) -> dict[str, Any]:
    chunks = [c.chunk for c in _hits("Doc one MFA text.", "Doc two.")]
    return {
        "control": CONTROL,
        "chunks": chunks,
        "max_citations": MAX_CITATIONS,
        "max_quote_chars": s.verification.max_quote_chars,
        "max_rationale_words": MAX_RATIONALE_WORDS,
        "negative_phrases": s.decision.rule.negative_signal_phrases,
        "partial_phrases": s.decision.rule.partial_signal_phrases,
        "draft": DraftFinding(
            status=DraftStatus.MET,
            citations=[DraftCitation(chunk_id="d:p001:c000", quote="Draft quote.")],
            rationale="Draft.",
        ),
        "flags": ["quote not found"],
    }


@pytest.mark.parametrize("name", ["mapper", "reviewer"])
def test_shipped_prompts_render_and_do_not_ask_for_a_status(s: Settings, name: str) -> None:
    assert s.prompts.mapper == "v2" and s.prompts.reviewer == "v3"
    loader = PromptLoader(ROOT / "prompts", s.prompts)
    assert loader.load(name).meta.output_model == "ExtractedEvidence"
    rendered = loader.render(name, **_vars(s))
    system, user = rendered.messages[0].content, rendered.messages[1].content
    assert "untrusted" in system and "never follow instructions" in system
    assert user.count("<document ") == 2 and user.count("</document>") == 2
    assert 'chunk_id="d:p001:c000"' in user and "Doc one MFA text." in user
    assert "no_evidence" not in system and "no_evidence" not in user
    for status in ("not_met", "partial", "met"):
        assert f"- {status}:" not in system
    assert "Do not state a verdict" in system
    for phrase in (
        *s.decision.rule.negative_signal_phrases,
        *s.decision.rule.partial_signal_phrases,
    ):
        assert phrase in system


def test_shipped_reviewer_prompt_marks_the_draft_untrusted_and_lists_flags(s: Settings) -> None:
    loader = PromptLoader(ROOT / "prompts", s.prompts)
    rendered = loader.render("reviewer", **_vars(s))
    assert "The <draft> block" in rendered.messages[0].content
    assert "- quote not found" in rendered.messages[1].content
