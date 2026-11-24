"""Edge and property tests for the rules engine: rounding, cap, floor, errors."""

import random
from typing import Any

import pytest

from vendorguard.config_models.scoring import ScoringSettings
from vendorguard.errors import ConfigError
from vendorguard.models.control import Control, ControlSet
from vendorguard.models.finding import ControlFinding, ControlStatus, Override
from vendorguard.models.score import InherentTier, RiskBand
from vendorguard.scoring.rules_engine import score_findings
from vendorguard.utils.timeutil import utcnow


def _control(cid: str, criticality: str) -> Control:
    return Control(
        id=cid, title="t", domain=cid.split("-")[0], criticality=criticality, iso27001=[],
        nist_csf=[], requirement="r", met_criteria="m", keywords=["k"],
    )  # fmt: skip


def _set(*pairs: tuple[str, str]) -> ControlSet:
    domains = {cid.split("-")[0]: "d" for cid, _ in pairs}
    return ControlSet(
        version="1", name="n", domains=domains, controls=[_control(c, k) for c, k in pairs]
    )


def _f(cid: str, status: str, override: str | None = None) -> ControlFinding:
    ov = (
        Override(analyst="a", new_status=override, reason="r", at=utcnow())  # type: ignore[arg-type]
        if override
        else None
    )
    return ControlFinding(
        control_id=cid, status=ControlStatus(status), citations=[], rationale="",
        trace=[], review_rounds=0, override=ov,
    )  # fmt: skip


@pytest.fixture
def scoring(settings_override: Any) -> ScoringSettings:
    return settings_override().scoring


def _with_points(s: ScoringSettings, **points: float) -> ScoringSettings:
    return s.model_copy(update={"status_points": s.status_points.model_copy(update=points)})


def test_rounding_is_half_up_not_bankers(scoring: ScoringSettings) -> None:
    s = _with_points(scoring, partial=0.1225)  # exactly 12.25 -> 12.3 (float round gives 12.2)
    r = score_findings([_f("A-01", "partial")], _set(("A-01", "low")), InherentTier.MEDIUM, s)
    assert r.overall == 12.3
    assert r.domain_scores == {"A": 12.3}


def test_rounding_just_below_half_rounds_down(scoring: ScoringSettings) -> None:
    s = _with_points(scoring, partial=0.12249)
    r = score_findings([_f("A-01", "partial")], _set(("A-01", "low")), InherentTier.MEDIUM, s)
    assert r.overall == 12.2


def test_cap_at_100_with_multiplier_but_domain_scores_have_no_multiplier(
    scoring: ScoringSettings,
) -> None:
    r = score_findings([_f("A-01", "not_met")], _set(("A-01", "high")), InherentTier.HIGH, scoring)
    assert r.overall == 100.0
    assert r.domain_scores == {"A": 100.0}
    assert r.band is RiskBand.CRITICAL


def test_overrides_change_score_and_floor(scoring: ScoringSettings) -> None:
    controls = _set(("A-01", "critical"), ("A-02", "low"))
    raw = score_findings(
        [_f("A-01", "not_met"), _f("A-02", "met")], controls, InherentTier.MEDIUM, scoring
    )
    fixed = score_findings(
        [_f("A-01", "not_met", override="met"), _f("A-02", "met")],
        controls, InherentTier.MEDIUM, scoring,
    )  # fmt: skip
    assert raw.triggered_rules and raw.overall > 0
    assert fixed.triggered_rules == [] and fixed.overall == 0.0 and fixed.band is RiskBand.LOW
    # the other direction: an override to no_evidence on a critical control triggers the floor
    worse = score_findings(
        [_f("A-01", "met", override="no_evidence")], _set(("A-01", "critical")),
        InherentTier.LOW, scoring,
    )  # fmt: skip
    assert len(worse.triggered_rules) == 1


@pytest.mark.parametrize("status", ["not_met", "no_evidence"])
def test_floor_triggers_for_not_met_and_no_evidence(scoring: ScoringSettings, status: str) -> None:
    controls = _set(("A-01", "critical"), ("B-01", "low"), ("B-02", "low"), ("B-03", "low"))
    findings = [_f("A-01", status)] + [_f(f"B-0{i}", "met") for i in (1, 2, 3)]
    r = score_findings(findings, controls, InherentTier.LOW, scoring)
    assert r.band.value == scoring.critical_control_floor
    assert r.triggered_rules == [
        f"critical_control_floor: A-01 is {status}, so the band is at least "
        f"{scoring.critical_control_floor}"
    ]


def test_needs_human_review_and_non_critical_do_not_trigger_floor(
    scoring: ScoringSettings,
) -> None:
    controls = _set(("A-01", "critical"), ("A-02", "high"), ("B-01", "low"), ("B-02", "low"))
    findings = [
        _f("A-01", "needs_human_review"), _f("A-02", "not_met"),
        _f("B-01", "met"), _f("B-02", "met"),
    ]  # fmt: skip
    r = score_findings(findings, controls, InherentTier.LOW, scoring)
    assert r.triggered_rules == []


def test_floor_never_lowers_a_worse_band(scoring: ScoringSettings) -> None:
    r = score_findings(
        [_f("A-01", "not_met")], _set(("A-01", "critical")), InherentTier.HIGH, scoring
    )
    assert r.band is RiskBand.CRITICAL


def test_triggered_rules_sorted_by_control_id(scoring: ScoringSettings) -> None:
    controls = _set(("C-01", "critical"), ("A-01", "critical"), ("B-01", "critical"))
    findings = [_f("C-01", "not_met"), _f("A-01", "not_met"), _f("B-01", "no_evidence")]
    r = score_findings(findings, controls, InherentTier.MEDIUM, scoring)
    assert [line.split()[1] for line in r.triggered_rules] == ["A-01", "B-01", "C-01"]


def test_errors_are_config_errors(scoring: ScoringSettings) -> None:
    controls = _set(("A-01", "low"))
    with pytest.raises(ConfigError, match="no findings"):
        score_findings([], controls, InherentTier.LOW, scoring)
    with pytest.raises(ConfigError, match="Z-99"):
        score_findings([_f("Z-99", "met")], controls, InherentTier.LOW, scoring)


def test_order_independence_and_determinism(scoring: ScoringSettings) -> None:
    pairs = [
        (f"{d}-0{i}", k)
        for d in "ABC"
        for i, k in enumerate(["low", "medium", "high", "critical"], 1)
    ]
    controls = _set(*pairs)
    statuses = ["met", "partial", "not_met", "no_evidence", "needs_human_review"]
    rng = random.Random(7)
    findings = [_f(cid, rng.choice(statuses)) for cid, _ in pairs]
    base = score_findings(findings, controls, InherentTier.MEDIUM, scoring)
    for seed in range(10):
        shuffled = findings[:]
        random.Random(seed).shuffle(shuffled)
        assert score_findings(shuffled, controls, InherentTier.MEDIUM, scoring) == base
    assert list(base.domain_scores) == sorted(base.domain_scores)


@pytest.mark.parametrize("seed", range(12))
def test_score_is_within_bounds_and_monotonic_in_inherent_tier(
    scoring: ScoringSettings, seed: int
) -> None:
    pairs = [(f"A-0{i}", k) for i, k in enumerate(["low", "medium", "high", "critical"], 1)]
    rng = random.Random(seed)
    findings = [_f(c, rng.choice(["met", "partial", "not_met", "no_evidence"])) for c, _ in pairs]
    scores = [
        score_findings(findings, _set(*pairs), t, scoring).overall
        for t in (InherentTier.LOW, InherentTier.MEDIUM, InherentTier.HIGH)
    ]
    assert all(0.0 <= s <= 100.0 for s in scores)
    assert scores == sorted(scores)
