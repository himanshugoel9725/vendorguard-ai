"""Inherent risk tier and the residual-risk score."""

from enum import StrEnum

from vendorguard.models._base import ContractModel, Score100


class InherentTier(StrEnum):
    """How risky the vendor is before looking at its controls."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskBand(StrEnum):
    """Band of the overall residual-risk score."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InherentRisk(ContractModel):
    """Inherent-risk tier with the reasons that produced it."""

    tier: InherentTier
    reasons: list[str]


class RiskScore(ContractModel):
    """Overall score (0-100), its band, per-domain scores and the hard rules that fired."""

    overall: Score100
    band: RiskBand
    domain_scores: dict[str, Score100]
    triggered_rules: list[str]


__all__ = ["InherentRisk", "InherentTier", "RiskBand", "RiskScore"]
