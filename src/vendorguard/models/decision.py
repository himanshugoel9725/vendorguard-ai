"""Decisions made by the triage and verify gates, and the trace of every gate taken."""

from enum import StrEnum

from vendorguard.models._base import ContractModel, NonEmptyStr, NonNegInt, Probability


class DecisionLabel(StrEnum):
    """Answers a decider can give. Triage uses the first two, verify the last two."""

    ADDRESSED = "addressed"
    NOT_ADDRESSED = "not_addressed"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class Decision(ContractModel):
    """A label with a confidence in [0, 1] and where it came from."""

    label: DecisionLabel
    confidence: Probability
    provider: NonEmptyStr
    reason: str | None = None
    fallback_used: bool = False


class Gate(StrEnum):
    """The checkpoints of the per-control cascade."""

    TRIAGE = "triage"
    CITATION = "citation"
    VERIFY = "verify"
    REVIEW = "review"


class GateTrace(ContractModel):
    """One arrow taken in the cascade. The citation gate records a ``Decision`` with provider
    ``citation_check`` (supported / unsupported, confidence 1.0)."""

    gate: Gate
    decision: Decision
    round: NonNegInt


__all__ = ["Decision", "DecisionLabel", "Gate", "GateTrace"]
