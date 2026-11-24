"""Tests for the pure re-assessment diff."""

from datetime import UTC, datetime

import pytest

from vendorguard.diff.reassessment import compute_diff
from vendorguard.models.finding import ControlFinding, ControlStatus, DraftStatus, Override
from vendorguard.models.run import AssessmentResult, CostSummary
from vendorguard.models.score import InherentRisk, InherentTier, RiskBand, RiskScore
from vendorguard.models.vendor import DataCategory, VendorProfile

S = ControlStatus
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _f(cid: str, status: ControlStatus, override: DraftStatus | None = None) -> ControlFinding:
    o = Override(analyst="a", new_status=override, reason="r", at=NOW) if override else None
    return ControlFinding(
        control_id=cid, status=status, citations=[], rationale="r", trace=[], review_rounds=0,
        override=o,
    )  # fmt: skip


def _score(overall: float) -> RiskScore:
    return RiskScore(overall=overall, band=RiskBand.LOW, domain_scores={}, triggered_rules=[])


def _prev(findings: list[ControlFinding], overall: float = 20.0) -> AssessmentResult:
    return AssessmentResult(
        run_id="run_prev", vendor_id="v", created_at=NOW,
        profile=VendorProfile(
            vendor_name="V", services=[], data_categories=[DataCategory.NONE], hosting=[],
            certifications=[], subprocessors=[],
        ),
        inherent_risk=InherentRisk(tier=InherentTier.LOW, reasons=[]),
        findings=sorted(findings, key=lambda f: f.control_id), score=_score(overall), summary="s",
        cost=CostSummary(
            llm_calls=0, cache_hits=0, tokens_in=0, tokens_out=0, decider_calls=0, usd=0
        ),
    )  # fmt: skip


def test_new_resolved_and_changed_are_found_and_sorted() -> None:
    prev = _prev([
        _f("A-01", S.MET), _f("B-02", S.PARTIAL), _f("C-03", S.NOT_MET), _f("D-04", S.NO_EVIDENCE),
        _f("E-05", S.MET), _f("F-06", S.PARTIAL),
    ])  # fmt: skip
    now = [
        _f("F-06", S.NOT_MET), _f("A-01", S.PARTIAL), _f("B-02", S.MET), _f("C-03", S.MET),
        _f("D-04", S.MET), _f("E-05", S.MET),
    ]  # fmt: skip
    d = compute_diff(now, _score(31.7), prev)
    assert d.previous_run_id == "run_prev"
    assert d.new_gaps == ["A-01"] and d.resolved_gaps == ["B-02", "C-03", "D-04"]
    assert [(c.control_id, c.from_status.value, c.to_status.value) for c in d.changed] == [
        ("A-01", "met", "partial"), ("B-02", "partial", "met"), ("C-03", "not_met", "met"),
        ("D-04", "no_evidence", "met"), ("F-06", "partial", "not_met"),
    ]  # fmt: skip
    assert d.score_delta == 11.7


def test_gap_to_worse_gap_is_a_change_not_a_new_gap() -> None:
    d = compute_diff([_f("A-01", S.NOT_MET)], _score(20.0), _prev([_f("A-01", S.PARTIAL)]))
    assert d.new_gaps == [] and d.resolved_gaps == [] and len(d.changed) == 1


def test_identical_runs_have_an_empty_diff_and_zero_delta() -> None:
    fs = [_f("A-01", S.MET), _f("B-02", S.PARTIAL)]
    d = compute_diff(fs, _score(20.0), _prev(fs))
    assert (d.new_gaps, d.resolved_gaps, d.changed, d.score_delta) == ([], [], [], 0.0)


def test_only_controls_in_both_runs_are_compared() -> None:
    prev = _prev([_f("A-01", S.MET), _f("B-02", S.MET)])
    d = compute_diff([_f("A-01", S.MET), _f("C-03", S.NOT_MET)], _score(20.0), prev)
    assert d.new_gaps == [] and d.changed == []  # B-02 and C-03 exist in one run only


def test_overrides_count_as_the_status() -> None:
    prev = _prev([_f("A-01", S.NOT_MET)])
    d = compute_diff([_f("A-01", S.NOT_MET, override=DraftStatus.MET)], _score(20.0), prev)
    assert d.resolved_gaps == ["A-01"]
    d2 = compute_diff(
        [_f("A-01", S.MET)], _score(20.0), _prev([_f("A-01", S.MET, DraftStatus.NOT_MET)])
    )
    assert d2.new_gaps == [] and d2.resolved_gaps == ["A-01"]


def test_needs_human_review_is_a_gap() -> None:
    d = compute_diff([_f("A-01", S.NEEDS_HUMAN_REVIEW)], _score(20.0), _prev([_f("A-01", S.MET)]))
    assert d.new_gaps == ["A-01"]


@pytest.mark.parametrize(
    ("new", "old", "delta"), [(0.3, 0.1, 0.2), (10.1, 10.0, 0.1), (5.0, 7.3, -2.3)]
)
def test_score_delta_has_no_float_noise(new: float, old: float, delta: float) -> None:
    assert (
        compute_diff([_f("A-01", S.MET)], _score(new), _prev([_f("A-01", S.MET)], old)).score_delta
        == delta
    )


def test_deterministic_for_any_finding_order() -> None:
    prev = _prev([_f("A-01", S.MET), _f("B-02", S.MET)])
    a = [_f("A-01", S.PARTIAL), _f("B-02", S.NOT_MET)]
    assert compute_diff(a, _score(30.0), prev) == compute_diff(a[::-1], _score(30.0), prev)
