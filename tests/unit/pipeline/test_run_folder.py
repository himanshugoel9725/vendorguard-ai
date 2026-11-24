"""The run folder: clean start for a repeated run, atomic canonical result file."""

import json
from datetime import UTC, datetime
from pathlib import Path

from vendorguard.models.finding import ControlFinding, ControlStatus
from vendorguard.models.run import AssessmentResult, CostSummary
from vendorguard.models.score import InherentRisk, InherentTier, RiskBand, RiskScore
from vendorguard.models.vendor import VendorProfile
from vendorguard.pipeline.run_folder import (
    AUDIT_FILE,
    MANIFEST_FILE,
    RESULT_FILE,
    persist_result,
    prepare_run_dir,
)


def _result(name: str = "Ünïcode Vendor ✓") -> AssessmentResult:
    return AssessmentResult(
        run_id="run-1", vendor_id="v", created_at=datetime(2026, 1, 1, tzinfo=UTC),
        profile=VendorProfile(
            vendor_name=name, services=[], data_categories=[], hosting=[], certifications=[],
            subprocessors=[],
        ),
        inherent_risk=InherentRisk(tier=InherentTier.LOW, reasons=[]),
        findings=[ControlFinding(
            control_id="IAM-01", status=ControlStatus.MET, citations=[], rationale="r",
            trace=[], review_rounds=0,
        )],
        score=RiskScore(overall=1.0, band=RiskBand.LOW, domain_scores={}, triggered_rules=[]),
        summary="s",
        cost=CostSummary(
            llm_calls=0, cache_hits=0, tokens_in=0, tokens_out=0, decider_calls=0, usd=0.0
        ),
    )  # fmt: skip


def test_prepare_creates_nested_folder(tmp_path: Path) -> None:
    d = prepare_run_dir(tmp_path / "a" / "runs", "run-1")
    assert d == tmp_path / "a" / "runs" / "run-1" and d.is_dir()


def test_prepare_removes_old_files_only(tmp_path: Path) -> None:
    d = prepare_run_dir(tmp_path, "r")
    for n in (AUDIT_FILE, MANIFEST_FILE, RESULT_FILE, "report.md"):
        (d / n).write_text("old")
    again = prepare_run_dir(tmp_path, "r")
    assert again == d
    assert [p.name for p in d.iterdir()] == ["report.md"]


def test_persist_writes_result_json_without_tmp(tmp_path: Path) -> None:
    d = prepare_run_dir(tmp_path, "r")
    path = persist_result(d, _result())
    assert path == d / RESULT_FILE
    assert [p.name for p in d.iterdir()] == [RESULT_FILE]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == "run-1" and data["profile"]["vendor_name"] == "Ünïcode Vendor ✓"
    assert AssessmentResult.model_validate(data) == _result()


def test_persist_is_deterministic_and_overwrites(tmp_path: Path) -> None:
    d = prepare_run_dir(tmp_path, "r")
    first = persist_result(d, _result()).read_bytes()
    persist_result(d, _result("other"))
    assert b"other" in (d / RESULT_FILE).read_bytes()
    assert persist_result(d, _result()).read_bytes() == first
