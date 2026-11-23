"""The control framework: controls grouped into a versioned set."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from vendorguard.errors import ConfigError
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
    keywords: Annotated[list[NonEmptyStr], Field(min_length=1)]

    @model_validator(mode="after")
    def _id_starts_with_domain(self) -> "Control":
        if not self.id.startswith(f"{self.domain}-"):
            raise ValueError(f"control id '{self.id}' must start with its domain '{self.domain}-'")
        return self


class ControlSet(ContractModel):
    """A versioned list of controls and the domain codes they use."""

    version: NonEmptyStr
    name: NonEmptyStr
    description: str = ""
    domains: dict[str, str]
    controls: list[Control]

    @model_validator(mode="after")
    def _controls_are_consistent(self) -> "ControlSet":
        ids = [c.id for c in self.controls]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate control ids: {', '.join(duplicates)}")
        unknown = sorted({c.domain for c in self.controls} - set(self.domains))
        if unknown:
            raise ValueError(f"controls use unknown domains: {', '.join(unknown)}")
        return self

    def subset(self, ids: Iterable[str]) -> "ControlSet":
        """Return a set holding only the controls with these IDs (sorted by ID).

        An empty ``ids`` gives an empty set: callers treat "no subset configured" as "all".
        """
        wanted = set(ids)
        missing = sorted(wanted - {c.id for c in self.controls})
        if missing:
            raise ConfigError(f"unknown control ids in subset: {', '.join(missing)}")
        kept = [c for c in self.controls if c.id in wanted]
        return self.model_copy(update={"controls": sorted(kept, key=lambda c: c.id)})


__all__ = ["Control", "ControlSet", "Criticality"]
