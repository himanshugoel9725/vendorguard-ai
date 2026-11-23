"""Assessment results, run manifests, re-assessment diffs and memory summaries."""

from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, model_validator

from vendorguard.models._base import ContractModel, NonEmptyStr, NonNegInt, Score100, Sha256
from vendorguard.models.finding import ControlFinding, ControlStatus
from vendorguard.models.score import InherentRisk, RiskBand, RiskScore
from vendorguard.models.vendor import VendorProfile


class StatusChange(ContractModel):
    """A control whose status differs between two runs."""

    control_id: NonEmptyStr
    from_status: ControlStatus
    to_status: ControlStatus


class ReassessmentDiff(ContractModel):
    """What changed since the vendor's previous assessment."""

    previous_run_id: NonEmptyStr
    new_gaps: list[str]
    resolved_gaps: list[str]
    changed: list[StatusChange]
    score_delta: float


class CostSummary(ContractModel):
    """Model usage and spend of one run."""

    llm_calls: NonNegInt
    cache_hits: NonNegInt
    tokens_in: NonNegInt
    tokens_out: NonNegInt
    decider_calls: NonNegInt
    usd: float


class AssessmentResult(ContractModel):
    """Everything an assessment produced. Findings are sorted by control ID."""

    run_id: NonEmptyStr
    vendor_id: NonEmptyStr
    created_at: AwareDatetime
    profile: VendorProfile
    inherent_risk: InherentRisk
    findings: list[ControlFinding]
    score: RiskScore
    diff: ReassessmentDiff | None = None
    summary: str
    cost: CostSummary
    manifest_path: Path | None = None

    @model_validator(mode="after")
    def _findings_sorted_and_unique(self) -> "AssessmentResult":
        ids = [f.control_id for f in self.findings]
        if ids != sorted(set(ids)):
            raise ValueError("findings must be unique and sorted by control_id")
        return self


class RunStatus(StrEnum):
    """Lifecycle of a run."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ManifestInput(ContractModel):
    """One input document of a run."""

    filename: NonEmptyStr
    sha256: Sha256
    pages: NonNegInt


class RunManifest(ContractModel):
    """Everything needed to reproduce and audit a run (never contains secrets)."""

    run_id: NonEmptyStr
    status: RunStatus
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    app_version: NonEmptyStr
    git_sha: str | None = None
    config_fingerprint: Sha256
    controls_version: NonEmptyStr
    prompt_hashes: dict[str, str]
    providers: dict[str, str]
    inputs: list[ManifestInput]
    result_hash: Sha256 | None = None


class AssessmentSummary(ContractModel):
    """One row of a vendor's assessment history."""

    run_id: NonEmptyStr
    vendor_id: NonEmptyStr
    created_at: AwareDatetime
    overall: Score100
    band: RiskBand


class VendorSummary(ContractModel):
    """One row of the vendor list."""

    vendor_id: NonEmptyStr
    name: NonEmptyStr
    runs: NonNegInt
    latest_band: RiskBand | None = None


class Answer(ContractModel):
    """The Ask Agent's reply, with the runs and controls it cites."""

    text: NonEmptyStr
    cited_run_ids: list[str]
    cited_control_ids: list[str]
    provider: NonEmptyStr


__all__ = [
    "Answer",
    "AssessmentResult",
    "AssessmentSummary",
    "CostSummary",
    "ManifestInput",
    "ReassessmentDiff",
    "RunManifest",
    "RunStatus",
    "StatusChange",
    "VendorSummary",
]
