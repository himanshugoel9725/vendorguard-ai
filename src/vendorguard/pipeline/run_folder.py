"""The folder of one run: audit log, manifest and result files."""

import re
from pathlib import Path

from vendorguard.errors import ConfigError
from vendorguard.models.run import AssessmentResult
from vendorguard.utils.jsonio import write_json

AUDIT_FILE = "audit.jsonl"
MANIFEST_FILE = "manifest.json"
RESULT_FILE = "result.json"


_OVERRIDE_EVENT = re.compile(r'"stage":\s*"analyst_override"')


def _has_overrides(audit_file: Path) -> bool:
    """True if the audit log records an analyst override (a text scan: a damaged log must not
    hide human decisions)."""
    if not audit_file.is_file():
        return False
    return (
        _OVERRIDE_EVENT.search(audit_file.read_text(encoding="utf-8", errors="replace")) is not None
    )


def prepare_run_dir(runs_dir: Path, run_id: str) -> Path:
    """Create ``runs_dir/<run_id>``. A repeated run (same deterministic ID) starts from clean
    audit, manifest, result and report files so its traces are never doubled or stale.

    A run that carries analyst overrides is never overwritten: they are human decisions.
    """
    run_dir = runs_dir / run_id
    if _has_overrides(run_dir / AUDIT_FILE):
        raise ConfigError(
            f"run {run_id} has analyst overrides and is not overwritten: "
            "move the folder away or use a different run id"
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in (AUDIT_FILE, MANIFEST_FILE, RESULT_FILE):
        (run_dir / name).unlink(missing_ok=True)
    for stale in run_dir.glob("report.*"):
        stale.unlink()
    return run_dir


def persist_result(run_dir: Path, result: AssessmentResult) -> Path:
    """Write the canonical ``result.json`` atomically and return its path."""
    path = run_dir / RESULT_FILE
    tmp = path.with_name(path.name + ".tmp")
    write_json(tmp, result.model_dump(mode="json"))
    tmp.replace(path)
    return path


__all__ = ["AUDIT_FILE", "MANIFEST_FILE", "RESULT_FILE", "persist_result", "prepare_run_dir"]
