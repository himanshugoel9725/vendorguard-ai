"""All four synthetic samples through the whole pipeline with the mock LLM (offline)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.eval.golden import load_golden
from vendorguard.observability.audit_log import read_audit_log
from vendorguard.observability.run_manifest import read_manifest, result_hash
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.reporting.facts import build_facts
from vendorguard.verification.summary_guard import check_summary

ROOT = Path(__file__).resolve().parents[2]
STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]
Make = Callable[..., Settings]
CASES = [(stem, ext) for stem in STEMS for ext in ("pdf", "txt")]
MIN_ACCURACY = 0.85  # PLAN 6.6; the mock measures 1.0 today, this is the floor, not the target


@pytest.mark.parametrize(("stem", "ext"), CASES)
def test_sample_matches_golden_and_leaves_every_artifact(
    settings_override: Make, stem: str, ext: str
) -> None:
    s = settings_override()
    golden = load_golden(ROOT / "data" / "golden" / f"{stem}.json")
    result = run_assessment(s, golden.vendor_id, [ROOT / "data" / "samples" / f"{stem}.{ext}"])
    hits = sum(f.status.value == golden.controls[f.control_id] for f in result.findings)
    assert len(result.findings) == len(golden.controls) == 25
    assert hits / len(result.findings) >= MIN_ACCURACY
    assert result.inherent_risk.tier is golden.expected_inherent_tier
    run_dir = s.paths.runs_dir / result.run_id
    for name in (
        "result.json",
        "manifest.json",
        "audit.jsonl",
        "report.json",
        "report.md",
        "report.html",
    ):
        assert (run_dir / name).is_file(), name
    assert read_manifest(run_dir / "manifest.json").result_hash == result_hash(result)
    stages = [e.stage for e in read_audit_log(run_dir / "audit.jsonl")]
    assert stages.count("cascade.finding") == 25
    assert all(f.status.value != "needs_human_review" for f in result.findings)


@pytest.mark.parametrize("stem", STEMS)
def test_result_hash_is_stable_across_two_runs(settings_override: Make, stem: str) -> None:
    doc = ROOT / "data" / "samples" / f"{stem}.pdf"
    first = run_assessment(settings_override(), "v", [doc])
    second = run_assessment(settings_override(), "v", [doc])
    assert first.run_id == second.run_id and result_hash(first) == result_hash(second)
    assert first.summary == second.summary


@pytest.mark.parametrize("stem", STEMS)
def test_summary_passes_the_number_guard_without_falling_back(
    settings_override: Make, stem: str
) -> None:
    s = settings_override()
    result = run_assessment(s, "v", [ROOT / "data" / "samples" / f"{stem}.pdf"])
    facts = build_facts(
        result.profile.vendor_name, result.inherent_risk, result.score, result.findings
    )
    assert check_summary(result.summary, facts, s.reporting.summary_max_words) == []
    stages = {e.stage for e in read_audit_log(s.paths.runs_dir / result.run_id / "audit.jsonl")}
    assert "reporter.fallback" not in stages


def test_the_injected_instruction_in_quillfield_does_not_change_any_finding(
    settings_override: Make,
) -> None:
    """Only quillfield carries an injected instruction (its spec has an ``injection`` block).
    The mock ignores instructions by design; a real model is measured in Phase 9."""
    golden = load_golden(ROOT / "data" / "golden" / "quillfield.json")
    result = run_assessment(
        settings_override(), golden.vendor_id, [ROOT / "data" / "samples" / "quillfield.pdf"]
    )
    assert {f.control_id: f.status.value for f in result.findings} == golden.controls
