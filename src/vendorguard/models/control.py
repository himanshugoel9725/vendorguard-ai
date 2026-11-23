"""The control framework: controls grouped into a versioned set."""

from enum import StrEnum

from pydantic import model_validator

from vendorguard.models._base import ContractModel, NonEmptyStr


class Criticality(StrEnum):
    """How much a control weighs in the overall score."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Control(ContractModel):
    """One baseline control with its framework mappings and matching keywords."""

    id: NonEmptyStr
    title: NonEmptyStr
    domain: NonEmptyStr
    criticality: Criticality
    iso27001: list[str]
    nist_csf: list[str]
    requirement: NonEmptyStr
    met_criteria: NonEmptyStr
    keywords: list[NonEmptyStr]


class ControlSet(ContractModel):
    """A versioned list of controls and the domain codes they use."""

    version: NonEmptyStr
    name: NonEmptyStr
    domains: dict[str, str]
    controls: list[Control]

    @model_validator(mode="after")
    def _controls_use_known_domains(self) -> "ControlSet":
        unknown = sorted({c.domain for c in self.controls} - set(self.domains))
        if unknown:
            raise ValueError(f"controls use unknown domains: {', '.join(unknown)}")
        return self


__all__ = ["Control", "ControlSet", "Criticality"]
