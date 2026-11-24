"""Tests for the analyst override flow (library and ``vg review``)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from vendorguard.cli.main import app
from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError
from vendorguard.models.control import Criticality
from vendorguard.models.finding import ControlStatus, DraftStatus
from vendorguard.models.score import RiskBand
from vendorguard.observability.audit_log import read_audit_log
from vendorguard.observability.run_manifest import read_manifest, result_hash
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.pipeline.override import apply_override
from vendorguard.pipeline.run_index import read_result
from vendorguard.reporting.facts import build_facts
from vendorguard.verification.summary_guard import check_summary

SAMPLE = Path(__file__).resolve().parents[3] / "data" / "samples" / "quillfield.txt"
Make = Callable[..., Settings]


@pytest.fixture
def run(settings_override: Make):  # type: ignore[no-untyped-def]
    s = settings_override()
    result = run_assessment(s, "quillfield", [SAMPLE])
    return s, load_controls(s.paths.controls_file), result, s.paths.runs_dir / result.run_id


def _pick(result, controls, *, critical: bool, met: bool) -> str:  # type: ignore[no-untyped-def]
    by_id = {c.id: c for c in controls.controls}
    for f in result.findings:
        is_critical = by_id[f.control_id].criticality is Criticality.CRITICAL
        if is_critical == critical and (f.status is ControlStatus.MET) == met:
            return f.control_id
    raise AssertionError("no such control in the sample")


def test_override_changes_the_score_the_reports_and_the_audit_log(run) -> None:  # type: ignore[no-untyped-def]
    s, controls, result, run_dir = run
    cid = _pick(result, controls, critical=False, met=True)
    new = apply_override(
        s, controls, run_dir, cid, DraftStatus.NOT_MET, "Seen in the audit", "Dana"
    )
    assert new.score.overall > result.score.overall
    finding = next(f for f in new.findings if f.control_id == cid)
    assert finding.status is ControlStatus.MET and finding.effective_status is ControlStatus.NOT_MET
    assert finding.override and finding.override.analyst == "Dana"
    assert read_result(run_dir) == new
    assert read_manifest(run_dir / "manifest.json").result_hash == result_hash(new)
    events = read_audit_log(run_dir / "audit.jsonl")
    assert [e.stage for e in events].count("analyst_override") == 1
    assert [e.seq for e in events] == sorted(e.seq for e in events)
    assert events[-1].control_id == cid and "Dana" not in events[-1].model_dump_json()
    md = (run_dir / "report.md").read_text(encoding="utf-8")
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "Dana" in md and "Dana" in html and "Seen in the audit" in html


def test_summary_stays_true_to_the_new_numbers(run) -> None:  # type: ignore[no-untyped-def]
    s, controls, result, run_dir = run
    cid = _pick(result, controls, critical=False, met=True)
    new = apply_override(s, controls, run_dir, cid, DraftStatus.NOT_MET, "r", "Dana")
    facts = build_facts(new.profile.vendor_name, new.inherent_risk, new.score, new.findings)
    assert check_summary(new.summary, facts, s.reporting.summary_max_words) == []
    assert f"{new.score.overall:g}" in new.summary and new.summary != result.summary


def test_overriding_a_critical_control_to_not_met_applies_the_floor_again(run) -> None:  # type: ignore[no-untyped-def]
    s, controls, result, run_dir = run
    cid = _pick(result, controls, critical=True, met=True)
    new = apply_override(s, controls, run_dir, cid, DraftStatus.NOT_MET, "r", "Dana")
    floor = RiskBand(s.scoring.critical_control_floor)
    assert any(cid in rule for rule in new.score.triggered_rules)
    order = list(RiskBand)
    assert order.index(new.score.band) >= order.index(floor)


def test_overriding_a_gap_to_met_lowers_the_score(run) -> None:  # type: ignore[no-untyped-def]
    s, controls, result, run_dir = run
    cid = _pick(result, controls, critical=False, met=False)
    new = apply_override(s, controls, run_dir, cid, DraftStatus.MET, "Evidence supplied", "Dana")
    assert new.score.overall < result.score.overall


def test_second_override_replaces_the_first_but_both_are_audited(run) -> None:  # type: ignore[no-untyped-def]
    s, controls, result, run_dir = run
    cid = _pick(result, controls, critical=False, met=True)
    apply_override(s, controls, run_dir, cid, DraftStatus.NOT_MET, "first", "Dana")
    new = apply_override(s, controls, run_dir, cid, DraftStatus.PARTIAL, "second", "Eli")
    finding = next(f for f in new.findings if f.control_id == cid)
    assert finding.override and finding.override.reason == "second"
    stages = [e.stage for e in read_audit_log(run_dir / "audit.jsonl")]
    assert stages.count("analyst_override") == 2


@pytest.mark.parametrize(
    ("control", "reason", "analyst"),
    [("NOPE-99", "r", "a"), ("IAM-02", "  ", "a"), ("IAM-02", "r", "")],
)
def test_bad_override_changes_nothing(run, control: str, reason: str, analyst: str) -> None:  # type: ignore[no-untyped-def]
    s, controls, result, run_dir = run
    before = (run_dir / "result.json").read_text(encoding="utf-8")
    with pytest.raises(ConfigError):
        apply_override(s, controls, run_dir, control, DraftStatus.MET, reason, analyst)
    assert (run_dir / "result.json").read_text(encoding="utf-8") == before
    assert "analyst_override" not in {e.stage for e in read_audit_log(run_dir / "audit.jsonl")}


def test_a_failed_run_cannot_be_reviewed(run) -> None:  # type: ignore[no-untyped-def]
    s, controls, _, run_dir = run
    manifest = read_manifest(run_dir / "manifest.json")
    from vendorguard.models.run import RunStatus
    from vendorguard.observability.run_manifest import write_manifest

    write_manifest(
        run_dir / "manifest.json", manifest.model_copy(update={"status": RunStatus.FAILED})
    )
    with pytest.raises(ConfigError, match="did not finish"):
        apply_override(s, controls, run_dir, "IAM-02", DraftStatus.MET, "r", "a")


def test_memory_store_receives_the_updated_result(run) -> None:  # type: ignore[no-untyped-def]
    s, controls, result, run_dir = run
    saved: list[Any] = []

    class Memory:
        def save_assessment(self, r: Any) -> None:
            saved.append(r)

    cid = _pick(result, controls, critical=False, met=True)
    new = apply_override(s, controls, run_dir, cid, DraftStatus.NOT_MET, "r", "a", memory=Memory())  # type: ignore[arg-type]
    assert saved == [new]


def test_vg_review_prints_the_score_change(run, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    s, controls, result, run_dir = run
    monkeypatch.setattr("vendorguard.cli.common.load_settings", lambda **_: s)
    cid = _pick(result, controls, critical=False, met=True)
    runner = CliRunner()
    ok = runner.invoke(
        app,
        ["review", result.run_id, cid, "--status", "not_met", "--reason", "r", "--analyst", "Dana"],
    )
    assert ok.exit_code == 0, ok.output
    assert "analyst override" in ok.output and "->" in ok.output
    bad = runner.invoke(
        app,
        ["review", result.run_id, "NOPE-99", "--status", "met", "--reason", "r", "--analyst", "a"],
    )
    assert bad.exit_code == 2 and "Traceback" not in bad.output
    worse = runner.invoke(
        app,
        [
            "review",
            result.run_id,
            cid,
            "--status",
            "needs_human_review",
            "--reason",
            "r",
            "--analyst",
            "a",
        ],
    )
    assert worse.exit_code == 2
