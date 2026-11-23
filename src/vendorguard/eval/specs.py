"""Sample-vendor specs: fictional vendor facts plus the true state of every control.

The specs are the ground truth behind the synthetic documents (``scripts/make_samples.py``) and the
golden labels in ``data/golden/``. ``missing`` means the document says nothing about the control, so
its golden status is ``no_evidence``.
"""

from collections import Counter
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import ValidationError

from vendorguard.errors import ConfigError
from vendorguard.models._base import ContractModel, NonEmptyStr
from vendorguard.models.finding import DraftStatus
from vendorguard.models.score import InherentTier
from vendorguard.models.vendor import DataCategory


class SampleState(StrEnum):
    """True state of a control in a sample vendor."""

    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"
    MISSING = "missing"

    def to_status(self) -> DraftStatus:
        """The status a perfect assessor would report (``missing`` becomes ``no_evidence``)."""
        if self is SampleState.MISSING:
            return DraftStatus.NO_EVIDENCE
        return DraftStatus(self.value)


class Injection(ContractModel):
    """A prompt-injection paragraph planted in one domain section (a regression test)."""

    section: NonEmptyStr
    text: NonEmptyStr


class SpecChanges(ContractModel):
    """For a year-2 spec: which gaps were fixed and which new gaps appeared."""

    fixed: list[str]
    new_gaps: list[str]


class VendorSpec(ContractModel):
    """One fictional vendor."""

    vendor_id: NonEmptyStr
    vendor_name: NonEmptyStr
    based_on: str | None = None
    report_period: NonEmptyStr
    summary: NonEmptyStr
    expected_inherent_tier: InherentTier
    services: list[NonEmptyStr]
    data_categories: list[DataCategory]
    hosting: list[NonEmptyStr]
    certifications: list[NonEmptyStr]
    subprocessors: list[NonEmptyStr]
    injection: Injection | None = None
    changes: SpecChanges | None = None
    controls: dict[str, SampleState]

    def counts(self) -> dict[SampleState, int]:
        """Number of controls in each state (all four states are always present)."""
        found = Counter(self.controls.values())
        return {state: found.get(state, 0) for state in SampleState}


def check_covers(spec: VendorSpec, control_ids: Iterable[str]) -> None:
    """Raise ConfigError unless the spec states every control ID, and only those."""
    expected = set(control_ids)
    given = set(spec.controls)
    problems = []
    if expected - given:
        problems.append(f"missing {', '.join(sorted(expected - given))}")
    if given - expected:
        problems.append(f"unknown {', '.join(sorted(given - expected))}")
    if problems:
        raise ConfigError(
            f"spec {spec.vendor_id}: control states are incomplete ({'; '.join(problems)})"
        )


def load_spec(path: Path) -> VendorSpec:
    """Load and validate one spec file; raises ConfigError with the file name on any problem."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return VendorSpec.model_validate(raw)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read spec {path}: {exc}") from exc
    except ValidationError as exc:
        fields = sorted(".".join(str(p) for p in e["loc"]) or "file" for e in exc.errors())
        raise ConfigError(f"invalid spec {path}: problems in {', '.join(fields)}") from exc


__all__ = [
    "Injection",
    "SampleState",
    "SpecChanges",
    "VendorSpec",
    "check_covers",
    "load_spec",
]
