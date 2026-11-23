"""One line of the audit log."""

from pydantic import AwareDatetime

from vendorguard.models._base import ContractModel, NonEmptyStr, NonNegInt
from vendorguard.models.decision import Decision


class AuditEvent(ContractModel):
    """A single recorded step: who did what, with hashes of its input and output."""

    run_id: NonEmptyStr
    seq: NonNegInt
    ts: AwareDatetime
    stage: NonEmptyStr
    actor: NonEmptyStr
    control_id: str | None = None
    input_hash: str
    output_hash: str
    decision: Decision | None = None
    tokens_in: NonNegInt
    tokens_out: NonNegInt
    usd: float
    latency_ms: float
    cached: bool


__all__ = ["AuditEvent"]
