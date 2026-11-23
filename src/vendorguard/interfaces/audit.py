"""Where agents and the pipeline write their audit events (implemented in task 6.1)."""

from typing import Protocol

from vendorguard.models.audit import AuditEvent
from vendorguard.models.decision import Decision


class AuditSink(Protocol):
    """Records one step of a run. The sink adds the run ID, the sequence number and the time."""

    def record(
        self,
        *,
        stage: str,
        actor: str,
        input_hash: str,
        output_hash: str,
        tokens_in: int,
        tokens_out: int,
        usd: float,
        latency_ms: float,
        cached: bool,
        control_id: str | None = None,
        decision: Decision | None = None,
    ) -> AuditEvent:
        """Store the event and return it."""
        ...


__all__ = ["AuditSink"]
