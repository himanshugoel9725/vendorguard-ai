"""Mapper Agent: reads the retrieved evidence for one control and drafts its status and quotes."""

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
    DraftStatus,
    ExtractedEvidence,
)
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.utils.prompt_loader import PromptLoader

NO_CHUNKS_RATIONALE = "No document text was retrieved for this control."


class MapperAgent(BaseAgent[ExtractedEvidence]):
    """At most one model call per control; citations are checked later by the citation checker."""

    name = "mapper"
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

    def map(self, control: Control, evidence: Sequence[ScoredChunk]) -> DraftFinding:
        """Draft the finding for ``control``; with no evidence at all no model is called."""
        if not evidence:
            return DraftFinding(
                status=DraftStatus.NO_EVIDENCE, citations=[], rationale=NO_CHUNKS_RATIONALE
            )
        chunks = sorted((hit.chunk for hit in evidence), key=lambda c: c.chunk_id)
        variables = {
            "control": control,
            "chunks": chunks,
            "max_citations": MAX_CITATIONS,
            "max_quote_chars": self._max_quote_chars,
            "max_rationale_words": MAX_RATIONALE_WORDS,
            "negative_phrases": self._rules.negative_signal_phrases,  # same list as the rules
            "partial_phrases": self._rules.partial_signal_phrases,
        }
        hints = {
            "keywords": control.keywords,
            "chunks": [{"chunk_id": c.chunk_id, "text": c.text} for c in chunks],
            "max_quote_chars": self._max_quote_chars,
        }
        extracted = self.run(variables, hints=hints, control_id=control.id)
        return derive_finding(control, extracted, self._rules)


__all__ = ["MapperAgent"]
