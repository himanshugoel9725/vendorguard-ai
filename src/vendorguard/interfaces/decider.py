"""The decision provider interface used by the triage and verify gates (docs/PLAN.md section 6)."""

from collections.abc import Sequence
from typing import Protocol

from vendorguard.models.control import Control
from vendorguard.models.decision import Decision
from vendorguard.models.evidence import ScoredChunk
from vendorguard.models.finding import DraftFinding


class Decider(Protocol):
    """Decides, one control at a time, whether a finding can be trusted."""

    name: str

    def triage(self, control: Control, evidence: Sequence[ScoredChunk]) -> Decision:
        """Is the control addressed at all in the evidence? (``addressed`` / ``not_addressed``)"""
        ...

    def verify(
        self, control: Control, draft: DraftFinding, evidence: Sequence[ScoredChunk]
    ) -> Decision:
        """Does the quoted evidence support the draft's status? (``supported`` / ``unsupported``)"""
        ...


__all__ = ["Decider"]
