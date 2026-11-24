"""Analyst override: replace one control's status, re-score, re-render and audit it."""

from pathlib import Path

from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.models.control import ControlSet
from vendorguard.models.finding import ControlFinding, DraftStatus, Override
from vendorguard.models.run import AssessmentResult, RunStatus
from vendorguard.observability.audit_log import AuditLog
from vendorguard.observability.run_manifest import read_manifest, result_hash, write_manifest
from vendorguard.pipeline.run_folder import AUDIT_FILE, MANIFEST_FILE, persist_result
from vendorguard.pipeline.run_index import read_result
from vendorguard.reporting.facts import build_facts
from vendorguard.reporting.fallback_summary import fallback_summary
from vendorguard.reporting.render import render_reports
from vendorguard.scoring.rules_engine import score_findings
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.timeutil import utcnow


def _check_text(name: str, value: str) -> str:
    if not value.strip():
        raise ConfigError(f"{name} must not be empty")
    return value


def apply_override(
    settings: Settings,
    controls: ControlSet,
    run_dir: Path,
    control_id: str,
    new_status: DraftStatus,
    reason: str,
    analyst: str,
    memory: MemoryStore | None = None,
) -> AssessmentResult:
    """Record the analyst's decision for ``control_id`` and return the updated result.

    The system's own status stays on the finding (``status``); the override sits beside it and
    the rules engine uses it. The score is recomputed (so the critical-control floor is applied
    again), the summary is rebuilt from the template (no model call: numbers must stay true),
    ``result.json``, the manifest's ``result_hash`` and all reports are rewritten, and one
    ``analyst_override`` audit event is added. A second override of the same control replaces
    the first one in the result; the audit log keeps both events.
    """
    result = read_result(run_dir)
    manifest = read_manifest(run_dir / MANIFEST_FILE)
    if manifest.status is not RunStatus.DONE:
        raise ConfigError(f"run {run_dir.name} did not finish: it cannot be reviewed")
    old = next((f for f in result.findings if f.control_id == control_id), None)
    if old is None:
        raise ConfigError(f"run {run_dir.name} has no finding for control '{control_id}'")
    override = Override(
        analyst=_check_text("analyst", analyst),
        new_status=new_status,
        reason=_check_text("reason", reason),
        at=utcnow(),
    )
    findings: list[ControlFinding] = [
        f.model_copy(update={"override": override}) if f is old else f for f in result.findings
    ]
    scored = controls.subset(f.control_id for f in findings)
    score = score_findings(findings, scored, result.inherent_risk.tier, settings.scoring)
    facts = build_facts(
        result.profile.vendor_name, result.inherent_risk, score, findings, result.diff
    )
    updated = result.model_copy(
        update={"findings": findings, "score": score, "summary": fallback_summary(facts)}
    )
    audit = AuditLog(run_dir / AUDIT_FILE, result.run_id)
    audit.record(
        stage="analyst_override",
        actor="analyst",
        control_id=control_id,
        input_hash=hash_obj({"control": control_id, "status": old.effective_status.value}),
        output_hash=hash_obj({"control": control_id, "status": new_status.value}),
        tokens_in=0,
        tokens_out=0,
        usd=0.0,
        latency_ms=0.0,
        cached=False,
    )
    persist_result(run_dir, updated)
    write_manifest(
        run_dir / MANIFEST_FILE, manifest.model_copy(update={"result_hash": result_hash(updated)})
    )
    render_reports(run_dir, controls, settings.reporting)
    if memory is not None:
        memory.save_assessment(updated)
    return updated


__all__ = ["apply_override"]
