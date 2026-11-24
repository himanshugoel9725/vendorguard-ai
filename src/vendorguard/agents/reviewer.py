"""Reviewer Agent: a second, wider look at one finding that a check flagged."""

from collections.abc import Sequence

from vendorguard.agents.base import BaseAgent
from vendorguard.agents.derive import derive_finding
from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.config_models.scoring import VerificationSettings
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.llm import LLMClient
from vendorguard.models.control import Control
from vendorguard.models.evidence import ScoredChunk
from vendorguard.models.finding import (
    MAX_CITATIONS,
    MAX_RATIONALE_WORDS,
    DraftFinding,
    ExtractedEvidence,
)
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.utils.prompt_loader import PromptLoader


class ReviewerAgent(BaseAgent[ExtractedEvidence]):
    """One model call per review round; the cascade checks the new citations again."""

    name = "reviewer"
    output_model = ExtractedEvidence

    def __init__(
        self,
        llm: LLMClient,
        prompts: PromptLoader,
        audit: AuditSink,
        cost: CostTracker,
        settings: VerificationSettings,
        rules: RuleDeciderSettings,
    ) -> None:
        super().__init__(llm, prompts, audit, cost)
        self._max_quote_chars = settings.max_quote_chars
        self._rules = rules

    def review(
        self,
        control: Control,
        draft: DraftFinding,
        flags: Sequence[str],
        evidence: Sequence[ScoredChunk],
    ) -> DraftFinding:
        """Revise ``draft`` given the ``flags`` (reasons only, never quote text) and the evidence.

        The caller passes ``top_k + review_extra_chunks`` chunks. Chunks are sorted by id.
        """
        chunks = sorted((hit.chunk for hit in evidence), key=lambda c: c.chunk_id)
        variables = {
            "control": control,
            "draft": draft,
            "flags": list(flags),
            "chunks": chunks,
            "max_citations": MAX_CITATIONS,
            "max_quote_chars": self._max_quote_chars,
            "max_rationale_words": MAX_RATIONALE_WORDS,
            "negative_phrases": self._rules.negative_signal_phrases,
            "partial_phrases": self._rules.partial_signal_phrases,
        }
        hints = {
            "keywords": control.keywords,
            "chunks": [{"chunk_id": c.chunk_id, "text": c.text} for c in chunks],
            "max_quote_chars": self._max_quote_chars,
        }
        extracted = self.run(variables, hints=hints, control_id=control.id)
        return derive_finding(control, extracted, self._rules, chunks)


__all__ = ["ReviewerAgent"]
