"""LLM-as-Jev: the same two gate questions as the rule decider, answered by one constrained call."""

from collections.abc import Sequence

from vendorguard.agents.base import BaseAgent
from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.llm import LLMClient
from vendorguard.models.control import Control
from vendorguard.models.decision import Decision, DecisionLabel
from vendorguard.models.evidence import ScoredChunk
from vendorguard.models.finding import DraftFinding, DraftStatus
from vendorguard.models.outputs import MAX_REASON_CHARS, JudgeOutput
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.utils.prompt_loader import PromptLoader

WRONG_LABEL_REASON = "The judge answered with a label that does not belong to this question."


class _JudgeAgent(BaseAgent[JudgeOutput]):
    name = "judge"
    output_model = JudgeOutput


class LlmJudgeDecider:
    """One model call per gate question; a label of the wrong kind degrades to the safe answer."""

    name = "llm_judge"

    def __init__(
        self,
        llm: LLMClient,
        prompts: PromptLoader,
        audit: AuditSink,
        cost: CostTracker,
        rules: RuleDeciderSettings,
    ) -> None:
        self._agent = _JudgeAgent(llm, prompts, audit, cost)
        self._rules = rules

    def _variables(
        self, control: Control, task: str, documents: list[dict[str, str]]
    ) -> dict[str, object]:
        return {
            "task": task,
            "control": control,
            "documents": documents,
            "max_reason_chars": MAX_REASON_CHARS,
            "negative_phrases": self._rules.negative_signal_phrases,
            "partial_phrases": self._rules.partial_signal_phrases,
        }

    def triage(self, control: Control, evidence: Sequence[ScoredChunk]) -> Decision:
        """Addressed or not; a wrong-kind label gives ``addressed`` at confidence 0 (never skip)."""
        chunks = sorted((e.chunk for e in evidence), key=lambda c: c.chunk_id)
        documents = [{"chunk_id": c.chunk_id, "text": c.text} for c in chunks]
        variables = self._variables(control, "triage", documents)
        variables["status"] = ""
        hints = {
            "task": "triage",
            "keywords": control.keywords,
            "evidence": [c.text for c in chunks],
            "top_score": max((e.vector_raw or 0.0 for e in evidence), default=0.0),
        }
        out = self._agent.run(variables, hints=hints, control_id=control.id)
        ok = out.label in (DecisionLabel.ADDRESSED, DecisionLabel.NOT_ADDRESSED)
        if ok:
            return self._decision(out)
        return Decision(
            label=DecisionLabel.ADDRESSED,
            confidence=0.0,
            provider=self.name,
            reason=WRONG_LABEL_REASON,
        )

    def verify(
        self, control: Control, draft: DraftFinding, evidence: Sequence[ScoredChunk]
    ) -> Decision:
        """Supported or not; a wrong-kind label means ``unsupported`` (goes to the Reviewer)."""
        quotes = [c.quote for c in draft.citations]
        documents = [{"chunk_id": c.chunk_id, "text": c.quote} for c in draft.citations]
        variables = self._variables(control, "verify", documents)
        variables["status"] = draft.status.value
        hints = {
            "task": "verify",
            "keywords": control.keywords,
            "status": draft.status.value if isinstance(draft.status, DraftStatus) else draft.status,
            "quotes": quotes,
        }
        out = self._agent.run(variables, hints=hints, control_id=control.id)
        if out.label in (DecisionLabel.SUPPORTED, DecisionLabel.UNSUPPORTED):
            return self._decision(out)
        return Decision(
            label=DecisionLabel.UNSUPPORTED,
            confidence=1.0,
            provider=self.name,
            reason=WRONG_LABEL_REASON,
        )

    def _decision(self, out: JudgeOutput) -> Decision:
        return Decision(
            label=out.label,
            confidence=out.confidence,
            provider=self.name,
            reason=out.reason or None,
        )


__all__ = ["LlmJudgeDecider"]
