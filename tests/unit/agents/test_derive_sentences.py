"""derive_finding reads the FULL source sentences of a quote (ADR-017)."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from vendorguard.agents.derive import derive_finding, source_sentences
from vendorguard.agents.mapper import MapperAgent
from vendorguard.agents.reviewer import ReviewerAgent
from vendorguard.config import Settings
from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import Control
from vendorguard.models.evidence import Chunk, DraftCitation, ScoredChunk
from vendorguard.models.finding import DraftStatus, ExtractedEvidence
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow

ROOT = Path(__file__).resolve().parents[3]
CONTROL = Control(
    id="ENC-01", title="Encryption at rest", domain="ENC", criticality="high",
    iso27001=["8.24"], nist_csf=["PR.DS"], requirement="Data is encrypted.",
    met_criteria="All data is encrypted at rest.", keywords=["encrypt", "MFA"],
)  # fmt: skip


def _chunk(text: str, n: int = 1) -> Chunk:
    return Chunk(chunk_id=f"d:p{n:03d}:c000", doc_id="d", page=n, text=text,
                 char_start=0, char_end=len(text))  # fmt: skip


def _ev(*quotes: str) -> ExtractedEvidence:
    return ExtractedEvidence(
        citations=[DraftCitation(chunk_id="d:p001:c000", quote=q) for q in quotes],
        rationale="r",
    )


@pytest.fixture
def s(settings_override: Callable[..., Settings]) -> Settings:
    return settings_override()


def test_clause_of_a_negative_sentence_is_not_met(s: Settings) -> None:
    chunks = [_chunk("Intro text. We do not encrypt all data at rest. Other.")]
    out = derive_finding(CONTROL, _ev("encrypt all data at rest"), s.decision.rule, chunks)
    assert out.status is DraftStatus.NOT_MET
    assert out.citations[0].quote == "encrypt all data at rest"  # citations stay the model's


def test_without_chunks_the_quote_alone_is_read(s: Settings) -> None:
    out = derive_finding(CONTROL, _ev("encrypt all data at rest"), s.decision.rule)
    assert out.status is DraftStatus.MET


def test_clause_of_a_partial_sentence_is_partial(s: Settings) -> None:
    phrase = s.decision.rule.partial_signal_phrases[0]
    chunks = [_chunk(f"MFA is {phrase} for staff. Done.")]
    out = derive_finding(CONTROL, _ev("MFA is"), s.decision.rule, chunks)
    assert out.status is DraftStatus.PARTIAL


def test_quote_spanning_two_sentences_reads_both(s: Settings) -> None:
    neg = s.decision.rule.negative_signal_phrases[0]
    text = f"MFA is available. Contractors {neg} use it."
    assert source_sentences(f"MFA is available. Contractors {neg} use it.", [_chunk(text)]) == [
        "MFA is available.", f"Contractors {neg} use it.",
    ]  # fmt: skip
    out = derive_finding(
        CONTROL,
        _ev(f"MFA is available. Contractors {neg} use it."),
        s.decision.rule,
        [_chunk(text)],
    )
    assert out.status is DraftStatus.NOT_MET


def test_chunk_order_does_not_matter(s: Settings) -> None:
    a, b = _chunk("We encrypt data.", 1), _chunk("We encrypt backups.", 2)
    assert source_sentences("encrypt", [a, b]) == source_sentences("encrypt", [b, a])
    assert source_sentences("encrypt", [b, a]) == ["We encrypt data.", "We encrypt backups."]


def test_quote_containing_whole_sentence_and_unmatched_fallback() -> None:
    chunk = _chunk("Alpha is here. Beta.")
    assert source_sentences("Intro. Alpha is here. More", [chunk]) == ["Alpha is here."]
    assert source_sentences("nothing like it", [chunk]) == ["nothing like it"]
    assert source_sentences("", [chunk]) == [""]


def test_keyword_check_uses_the_sentences(s: Settings) -> None:
    chunks = [_chunk("MFA protects every login today.")]
    # the clause has no keyword, the full sentence has one
    assert derive_finding(CONTROL, _ev("protects every login"), s.decision.rule).status is (
        DraftStatus.NO_EVIDENCE
    )
    out = derive_finding(CONTROL, _ev("protects every login"), s.decision.rule, chunks)
    assert out.status is DraftStatus.MET


def test_curly_quotes_and_case_are_normalised(s: Settings) -> None:
    chunks = [_chunk("We don’t ENCRYPT data — ever.")]
    out = derive_finding(CONTROL, _ev("we don't encrypt data - ever."), s.decision.rule, chunks)
    assert out.status is DraftStatus.NOT_MET
    assert source_sentences("encrypt data", chunks) == ["We don’t ENCRYPT data — ever."]


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

    def complete_json(
        self, messages: Sequence[ChatMessage], output_model: type[Any], *, purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[Any]:  # fmt: skip
        return LLMResult(parsed=self.parsed, usage=Usage(tokens_in=1, tokens_out=1),
                         provider="ollama", model="fake")  # fmt: skip


def test_mapper_and_reviewer_pass_their_chunks_to_the_derivation(s: Settings) -> None:
    hits = [ScoredChunk(chunk=_chunk("We do not encrypt all data at rest."), score=1.0, bm25=1.0)]
    llm = Fixed(_ev("encrypt all data at rest"))
    prompts = PromptLoader(ROOT / "prompts", s.prompts)
    args = (prompts, FakeAudit(), CostTracker(s.cost), s.verification, s.decision.rule)
    draft = MapperAgent(llm, *args).map(CONTROL, hits)
    assert draft.status is DraftStatus.NOT_MET
    review = ReviewerAgent(llm, *args).review(CONTROL, draft, ["flag"], hits)
    assert review.status is DraftStatus.NOT_MET
