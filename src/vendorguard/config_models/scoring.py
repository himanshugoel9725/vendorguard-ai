"""Settings sections for citation verification and the deterministic scoring engine."""

from typing import Annotated

from pydantic import Field, model_validator

from vendorguard.config_models.base import (
    Criticality,
    FindingStatus,
    PositiveFloat,
    PositiveInt,
    Probability,
    StrictModel,
)


class VerificationSettings(StrictModel):
    """Citation checking."""

    citation_min_similarity: Probability
    max_quote_chars: PositiveInt
    require_citation_for: list[FindingStatus]


class CriticalityWeights(StrictModel):
    """Weight of each control criticality in the overall score (all > 0)."""

    low: PositiveFloat
    medium: PositiveFloat
    high: PositiveFloat
    critical: PositiveFloat


class StatusPoints(StrictModel):
    """Residual-risk points per finding status: 0 = no risk, 1 = full risk."""

    met: Probability
    partial: Probability
    not_met: Probability
    no_evidence: Probability
    needs_human_review: Probability


class InherentRiskMultiplier(StrictModel):
    """Score multiplier per inherent-risk tier (all > 0)."""

    low: PositiveFloat
    medium: PositiveFloat
    high: PositiveFloat


class InherentRiskSettings(StrictModel):
    """Which data categories raise the inherent-risk tier."""

    high_if_any: list[str]
    medium_if_any: list[str]
    multiplier: InherentRiskMultiplier


class BandSettings(StrictModel):
    """Inclusive upper bound of each risk band on the 0-100 scale."""

    low: Annotated[int, Field(ge=0, le=100)]
    medium: Annotated[int, Field(ge=0, le=100)]
    high: Annotated[int, Field(ge=0, le=100)]
    critical: Annotated[int, Field(ge=0, le=100)]

    @model_validator(mode="after")
    def _ascending_to_100(self) -> "BandSettings":
        if not self.low < self.medium < self.high < self.critical:
            raise ValueError("bands must be strictly ascending: low < medium < high < critical")
        if self.critical != 100:
            raise ValueError("the critical band must end at 100")
        return self


class ScoringSettings(StrictModel):
    """Rules-engine parameters."""

    criticality_weights: CriticalityWeights
    status_points: StatusPoints
    inherent_risk: InherentRiskSettings
    bands: BandSettings
    critical_control_floor: Criticality


__all__ = [
    "BandSettings",
    "CriticalityWeights",
    "InherentRiskMultiplier",
    "InherentRiskSettings",
    "ScoringSettings",
    "StatusPoints",
    "VerificationSettings",
]
