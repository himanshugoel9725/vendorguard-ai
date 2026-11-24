"""The folder of one run: audit log, manifest and result files."""

from pathlib import Path

from vendorguard.models.run import AssessmentResult
from vendorguard.utils.jsonio import write_json

AUDIT_FILE = "audit.jsonl"
MANIFEST_FILE = "manifest.json"
RESULT_FILE = "result.json"


def prepare_run_dir(runs_dir: Path, run_id: str) -> Path:
    """Create ``runs_dir/<run_id>``. A repeated run (same deterministic ID) starts from clean
    audit, manifest and result files so its traces are never doubled."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in (AUDIT_FILE, MANIFEST_FILE, RESULT_FILE):
        (run_dir / name).unlink(missing_ok=True)
    return run_dir


def persist_result(run_dir: Path, result: AssessmentResult) -> Path:
    """Write the canonical ``result.json`` atomically and return its path."""
    path = run_dir / RESULT_FILE
    tmp = path.with_name(path.name + ".tmp")
    write_json(tmp, result.model_dump(mode="json"))
    tmp.replace(path)
    return path


__all__ = ["AUDIT_FILE", "MANIFEST_FILE", "RESULT_FILE", "persist_result", "prepare_run_dir"]
