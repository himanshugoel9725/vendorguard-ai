"""Fallback decider: a failing or unavailable primary decider never stops a run."""

import logging
from collections.abc import Sequence

from vendorguard.errors import ProviderError, SchemaValidationError
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.decider import Decider
from vendorguard.models.control import Control
from vendorguard.models.decision import Decision
from vendorguard.models.evidence import ScoredChunk
from vendorguard.models.finding import DraftFinding
from vendorguard.utils.hashing import hash_obj

log = logging.getLogger(__name__)
STAGE = "decider_fallback"


class FallbackDecider:
    """Uses ``primary``; on a provider error (or when it is ``None``) the fallback decides.

    Every fallback decision is marked ``fallback_used`` and gets a ``decider_fallback`` audit event
    naming the gate and the error class (never the error text). One warning is logged per run.
    """

    def __init__(
        self,
        primary: Decider | None,
        fallback: Decider,
        audit: AuditSink,
        *,
        primary_name: str,
        unavailable: str = "",
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._audit = audit
        self.name = primary_name
        self._unavailable = unavailable
        self._warned = False
        if primary is None:
            self._warn(unavailable or "the primary decider is not available")

    def triage(self, control: Control, evidence: Sequence[ScoredChunk]) -> Decision:
        """Triage with the primary decider, or with the fallback if it fails."""
        if self._primary is not None:
            try:
                return self._primary.triage(control, evidence)
            except (ProviderError, SchemaValidationError) as exc:
                self._switch("triage", control.id, type(exc).__name__)
        else:
            self._switch("triage", control.id, "Unavailable")
        return self._fallback.triage(control, evidence).model_copy(update={"fallback_used": True})

    def verify(
        self, control: Control, draft: DraftFinding, evidence: Sequence[ScoredChunk]
    ) -> Decision:
        """Verify with the primary decider, or with the fallback if it fails."""
        if self._primary is not None:
            try:
                return self._primary.verify(control, draft, evidence)
            except (ProviderError, SchemaValidationError) as exc:
                self._switch("verify", control.id, type(exc).__name__)
        else:
            self._switch("verify", control.id, "Unavailable")
        return self._fallback.verify(control, draft, evidence).model_copy(
            update={"fallback_used": True}
        )

    def _warn(self, why: str) -> None:
        if not self._warned:
            self._warned = True
            log.warning(
                "decider %s unavailable (%s): using %s", self.name, why, self._fallback.name
            )

    def _switch(self, gate: str, control_id: str, error: str) -> None:
        self._warn(error)
        self._audit.record(
            stage=STAGE,
            actor=f"{self.name}->{self._fallback.name}",
            control_id=control_id,
            input_hash=hash_obj({"gate": gate, "control_id": control_id}),
            output_hash=hash_obj({"error": error}),
            tokens_in=0,
            tokens_out=0,
            usd=0.0,
            latency_ms=0.0,
            cached=False,
        )


__all__ = ["FallbackDecider"]
