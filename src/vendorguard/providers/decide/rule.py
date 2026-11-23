"""Rule decider: keyword and signal rules, no model, no cost, fully deterministic."""

from collections.abc import Sequence

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.control import Control
from vendorguard.models.decision import Decision
from vendorguard.models.evidence import ScoredChunk
from vendorguard.models.finding import DraftFinding
from vendorguard.verification.rule_logic import Verdict, triage_verdict, verify_verdict


class RuleDecider:
    """Implements the ``Decider`` protocol with the shared rules in ``verification/rule_logic``."""

    name = "rule"

    def __init__(self, rules: RuleDeciderSettings) -> None:
        self._rules = rules

    def triage(self, control: Control, evidence: Sequence[ScoredChunk]) -> Decision:
        """Addressed if keyword hits or the best raw cosine similarity pass their thresholds."""
        top = max((e.vector_raw or 0.0 for e in evidence), default=0.0)
        verdict = triage_verdict(
            [e.chunk.text for e in evidence], control.keywords, top, self._rules
        )
        return self._decision(verdict)

    def verify(
        self, control: Control, draft: DraftFinding, evidence: Sequence[ScoredChunk]
    ) -> Decision:
        """Supported if the quotes cover the keywords and read as the drafted status."""
        quotes = [c.quote for c in draft.citations]
        return self._decision(verify_verdict(draft.status, quotes, control.keywords, self._rules))

    def _decision(self, verdict: Verdict) -> Decision:
        return Decision(
            label=verdict.label,
            confidence=verdict.confidence,
            provider=self.name,
            reason=f"Rules: {len(verdict.hits)} keyword(s) matched.",
        )


__all__ = ["RuleDecider"]
