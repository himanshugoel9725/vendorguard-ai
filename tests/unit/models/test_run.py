"""Tests for vendorguard.models.run, including hashing determinism."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from vendorguard.models.decision import Decision, DecisionLabel, Gate, GateTrace
from vendorguard.models.finding import ControlFinding, ControlStatus
from vendorguard.models.run import (
    Answer,
    AssessmentResult,
    AssessmentSummary,
    CostSummary,
    ManifestInput,
    ReassessmentDiff,
    RunManifest,
    RunStatus,
    StatusChange,
    VendorSummary,
)
from vendorguard.models.score import InherentRisk, InherentTier, RiskBand, RiskScore
from vendorguard.models.vendor import DataCategory, VendorProfile
from vendorguard.utils.hashing import hash_obj

NOW = datetime(2025, 1, 1, tzinfo=UTC)
SHA = "ab" * 32


def make_finding(cid: str, status: ControlStatus = ControlStatus.MET) -> ControlFinding:
    return ControlFinding(
        control_id=cid,
        status=status,
        citations=[],
        rationale="r",
        trace=[
            GateTrace(
                gate=Gate.TRIAGE,
                decision=Decision(label=DecisionLabel.ADDRESSED, confidence=0.9, provider="m"),
                round=0,
            )
        ],
        review_rounds=0,
    )


def make_cost() -> CostSummary:
    return CostSummary(
        llm_calls=1, cache_hits=0, tokens_in=10, tokens_out=5, decider_calls=2, usd=0.0
    )


def make_result(findings: list[ControlFinding] | None = None, **kw: object) -> AssessmentResult:
    if findings is None:
        findings = [make_finding("AC-01"), make_finding("AC-02")]
    data: dict = {
        "run_id": "r1",
        "vendor_id": "v1",
        "created_at": NOW,
        "profile": VendorProfile(
            vendor_name="Acme",
            services=["crm"],
            data_categories=[DataCategory.PII],
            hosting=[],
            certifications=[],
            subprocessors=[],
        ),
        "inherent_risk": InherentRisk(tier=InherentTier.MEDIUM, reasons=["pii"]),
        "findings": findings,
        "score": RiskScore(
            overall=10.0, band=RiskBand.LOW, domain_scores={"AC": 10.0}, triggered_rules=[]
        ),
        "summary": "s",
        "cost": make_cost(),
    }
    data.update(kw)
    return AssessmentResult(**data)


def make_manifest(**kw: object) -> RunManifest:
    data: dict = {
        "run_id": "r1",
        "status": RunStatus.RUNNING,
        "started_at": NOW,
        "app_version": "0.1",
        "config_fingerprint": SHA,
        "controls_version": "1",
        "prompt_hashes": {"p": "h"},
        "providers": {"llm": "mock"},
        "inputs": [ManifestInput(filename="f.pdf", sha256=SHA, pages=3)],
    }
    data.update(kw)
    return RunManifest(**data)


def test_status_change_and_diff_roundtrip() -> None:
    sc = StatusChange(
        control_id="AC-01", from_status=ControlStatus.MET, to_status=ControlStatus.NOT_MET
    )
    d = ReassessmentDiff(
        previous_run_id="r0", new_gaps=["AC-01"], resolved_gaps=[], changed=[sc], score_delta=-2.5
    )
    assert ReassessmentDiff.model_validate_json(d.model_dump_json()) == d
    with pytest.raises(ValidationError):
        StatusChange(control_id="AC-01", from_status="bogus", to_status="met")


@pytest.mark.parametrize(
    "field", ["llm_calls", "cache_hits", "tokens_in", "tokens_out", "decider_calls"]
)
def test_cost_counters_non_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        CostSummary(**{**make_cost().model_dump(), field: -1})


def test_result_roundtrip_and_defaults() -> None:
    r = make_result()
    assert r.diff is None
    assert r.manifest_path is None
    assert AssessmentResult.model_validate_json(r.model_dump_json()) == r


def test_result_optional_fields() -> None:
    diff = ReassessmentDiff(
        previous_run_id="r0", new_gaps=[], resolved_gaps=[], changed=[], score_delta=0.0
    )
    r = make_result(manifest_path=Path("runs/r1/manifest.json"), diff=diff)
    assert isinstance(r.manifest_path, Path)
    assert AssessmentResult.model_validate_json(r.model_dump_json()) == r


def test_result_empty_findings_ok() -> None:
    assert make_result(findings=[]).findings == []


@pytest.mark.parametrize(
    "ids", [["AC-02", "AC-01"], ["AC-01", "AC-01"], ["AC-01", "AC-02", "AC-01"]]
)
def test_result_rejects_unsorted_or_duplicate(ids: list[str]) -> None:
    with pytest.raises(ValidationError):
        make_result(findings=[make_finding(i) for i in ids])


def test_result_frozen_extra() -> None:
    with pytest.raises(ValidationError):
        make_result().summary = "x"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        make_result(bogus=1)
    with pytest.raises(ValidationError):
        make_result(created_at=datetime(2025, 1, 1))


def test_run_status_values() -> None:
    assert [s.value for s in RunStatus] == ["running", "done", "failed"]


def test_manifest_input_sha() -> None:
    with pytest.raises(ValidationError):
        ManifestInput(filename="f", sha256="XYZ", pages=1)
    with pytest.raises(ValidationError):
        ManifestInput(filename="f", sha256=SHA, pages=-1)


def test_manifest_defaults_and_roundtrip() -> None:
    m = make_manifest()
    assert (m.finished_at, m.git_sha, m.result_hash) == (None, None, None)
    assert RunManifest.model_validate_json(m.model_dump_json()) == m
    full = make_manifest(status=RunStatus.DONE, finished_at=NOW, git_sha="abc123", result_hash=SHA)
    assert RunManifest.model_validate_json(full.model_dump_json()) == full


@pytest.mark.parametrize("fp", ["short", "G" * 64, "A" * 64, ""])
def test_manifest_fingerprint_rejected(fp: str) -> None:
    with pytest.raises(ValidationError):
        make_manifest(config_fingerprint=fp)


def test_manifest_requires_fingerprint_and_aware() -> None:
    data = make_manifest().model_dump()
    del data["config_fingerprint"]
    with pytest.raises(ValidationError):
        RunManifest(**data)
    with pytest.raises(ValidationError):
        make_manifest(started_at=datetime(2025, 1, 1))
    with pytest.raises(ValidationError):
        make_manifest(result_hash="nothex")


def test_summaries() -> None:
    a = AssessmentSummary(
        run_id="r", vendor_id="v", created_at=NOW, overall=50.0, band=RiskBand.HIGH
    )
    assert AssessmentSummary.model_validate_json(a.model_dump_json()) == a
    with pytest.raises(ValidationError):
        AssessmentSummary(
            run_id="r", vendor_id="v", created_at=NOW, overall=101.0, band=RiskBand.HIGH
        )
    v = VendorSummary(vendor_id="v", name="Acme", runs=0)
    assert v.latest_band is None
    v2 = VendorSummary(vendor_id="v", name="Acme", runs=2, latest_band=RiskBand.LOW)
    assert VendorSummary.model_validate_json(v2.model_dump_json()) == v2
    with pytest.raises(ValidationError):
        VendorSummary(vendor_id="v", name="Acme", runs=-1)


def test_answer() -> None:
    a = Answer(text="t", cited_run_ids=["r"], cited_control_ids=[], provider="mock")
    assert Answer.model_validate_json(a.model_dump_json()) == a
    with pytest.raises(ValidationError):
        Answer(text="", cited_run_ids=[], cited_control_ids=[], provider="mock")
    with pytest.raises(ValidationError):
        Answer(text="t", cited_run_ids=[], cited_control_ids=[], provider="")


def test_hash_deterministic_and_sensitive() -> None:
    a, b = make_result(), make_result()
    assert a == b
    assert hash_obj(a) == hash_obj(b)
    assert hash_obj(AssessmentResult.model_validate_json(a.model_dump_json())) == hash_obj(a)
    changed = make_result(
        findings=[make_finding("AC-01", ControlStatus.NOT_MET), make_finding("AC-02")]
    )
    assert hash_obj(changed) != hash_obj(a)
