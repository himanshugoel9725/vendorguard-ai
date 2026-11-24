"""Read the run folders under ``paths.runs_dir`` (for the CLI and, later, the API)."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vendorguard.errors import ConfigError
from vendorguard.models.run import AssessmentResult, RunManifest, RunStatus
from vendorguard.observability.run_manifest import read_manifest
from vendorguard.pipeline.run_folder import MANIFEST_FILE, RESULT_FILE
from vendorguard.utils.jsonio import read_json

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VENDOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class RunInfo:
    """One row of the run list. Failed runs have a manifest but no result."""

    run_id: str
    status: RunStatus
    started_at: datetime
    vendor_id: str | None
    overall: float | None
    band: str | None
    path: Path


def run_path(runs_dir: Path, run_id: str) -> Path:
    """The folder of a run; the ID is checked so it can never point outside ``runs_dir``."""
    if not RUN_ID_PATTERN.match(run_id):
        raise ConfigError(f"'{run_id}' is not a valid run id")
    path = runs_dir / run_id
    if not path.is_dir():
        raise ConfigError(f"run '{run_id}' not found in {runs_dir}")
    return path


def read_result(run_dir: Path) -> AssessmentResult:
    """The saved result of a finished run."""
    file = run_dir / RESULT_FILE
    if not file.is_file():
        raise ConfigError(f"run {run_dir.name} has no result (it did not finish)")
    try:
        return AssessmentResult.model_validate(read_json(file))
    except ValueError as exc:
        raise ConfigError(f"result of run {run_dir.name} is damaged") from exc


def _info(run_dir: Path, manifest: RunManifest) -> RunInfo:
    vendor = overall = band = None
    if (run_dir / RESULT_FILE).is_file():
        result = read_result(run_dir)
        vendor, overall, band = result.vendor_id, result.score.overall, result.score.band.value
    return RunInfo(
        run_id=manifest.run_id,
        status=manifest.status,
        started_at=manifest.started_at,
        vendor_id=vendor,
        overall=overall,
        band=band,
        path=run_dir,
    )


def list_runs(runs_dir: Path, vendor_id: str | None = None) -> list[RunInfo]:
    """All runs, newest first (ties by run id). Folders without a manifest are skipped."""
    if not runs_dir.is_dir():
        return []
    found = []
    for run_dir in runs_dir.iterdir():
        if (run_dir / MANIFEST_FILE).is_file():
            info = _info(run_dir, read_manifest(run_dir / MANIFEST_FILE))
            if vendor_id is None or info.vendor_id == vendor_id:
                found.append(info)
    return sorted(found, key=lambda r: (-r.started_at.timestamp(), r.run_id))


__all__ = ["RUN_ID_PATTERN", "VENDOR_ID_PATTERN", "RunInfo", "list_runs", "read_result", "run_path"]
