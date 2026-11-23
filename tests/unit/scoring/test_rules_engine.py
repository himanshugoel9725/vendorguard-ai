"""Rules engine and bands: hand-computed cases must match exactly."""

from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.scoring import ScoringSettings
from vendorguard.errors import ConfigError
from vendorguard.models.control import Control, ControlSet
from vendorguard.models.finding import ControlFinding, ControlStatus, Override
from vendorguard.models.score import InherentTier, RiskBand
from vendorguard.scoring.bands import at_least, band_for
from vendorguard.scoring.rules_engine import score_findings
from vendorguard.utils.timeutil import utcnow


def _control(cid: str, criticality: str) -> Control:
    return Control(
        id=cid, title="t", domain=cid.split("-")[0], criticality=criticality, iso27001=[],
        nist_csf=[], requirement="r", met_criteria="m", keywords=["k"],
    )  # fmt: skip


# weights from settings.yaml: low 1, medium 2, high 3, critical 5 (total 11)
CONTROLS = ControlSet(
    version="1", name="n", domains={"A": "a", "B": "b"},
    controls=[_control("A-01", "critical"), _control("A-02", "low"),
              _control("B-01", "high"), _control("B-02", "medium")],
)  # fmt: skip


@pytest.fixture
def scoring(settings_override: Any) -> ScoringSettings:
    s: Settings = settings_override()
    return s.scoring


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


def _all(
    a1: str = "met", a2: str = "met", b1: str = "met", b2: str = "met"
) -> list[ControlFinding]:
    return [_f("A-01", a1), _f("A-02", a2), _f("B-01", b1), _f("B-02", b2)]


def test_all_met_is_zero_and_low(scoring: ScoringSettings) -> None:
    r = score_findings(_all(), CONTROLS, InherentTier.MEDIUM, scoring)
    assert (r.overall, r.band, r.triggered_rules) == (0.0, RiskBand.LOW, [])
    assert r.domain_scores == {"A": 0.0, "B": 0.0}


def test_critical_not_met_raises_the_band_to_the_floor(scoring: ScoringSettings) -> None:
    # 5 / 11 = 45.4545 -> 45.5 is "medium", but a critical control is not met: at least high
    r = score_findings(_all(a1="not_met"), CONTROLS, InherentTier.MEDIUM, scoring)
    assert r.overall == 45.5 and r.band is RiskBand.HIGH
    assert r.triggered_rules == [
        "critical_control_floor: A-01 is not_met, so the band is at least high"
    ]
    assert r.domain_scores == {"A": 83.3, "B": 0.0}  # 5 / 6 = 83.33


def test_mixed_statuses_and_every_inherent_multiplier(scoring: ScoringSettings) -> None:
    findings = _all(a2="no_evidence", b1="partial", b2="needs_human_review")
    # risk = 0.8*1 + 0.5*3 + 0.6*2 = 3.5; 3.5 / 11 = 31.818...
    got = {
        t: score_findings(findings, CONTROLS, t, scoring).overall
        for t in (InherentTier.LOW, InherentTier.MEDIUM, InherentTier.HIGH)
    }
    assert got == {InherentTier.LOW: 25.5, InherentTier.MEDIUM: 31.8, InherentTier.HIGH: 38.2}
    r = score_findings(findings, CONTROLS, InherentTier.MEDIUM, scoring)
    assert r.domain_scores == {"A": 13.3, "B": 54.0} and r.band is RiskBand.MEDIUM
    assert r.triggered_rules == []  # the critical control is met


def test_overrides_are_respected(scoring: ScoringSettings) -> None:
    r = score_findings(
        [_f("A-01", "not_met", "met"), *_all()[1:]],
        CONTROLS, InherentTier.MEDIUM, scoring,
    )  # fmt: skip
    assert r.overall == 0.0 and r.triggered_rules == []
    r2 = score_findings(
        [_f("A-01", "met", "no_evidence"), *_all()[1:]], CONTROLS, InherentTier.MEDIUM, scoring
    )
    assert r2.band is RiskBand.HIGH and len(r2.triggered_rules) == 1


def test_score_is_capped_at_100(scoring: ScoringSettings) -> None:
    r = score_findings(
        _all("not_met", "not_met", "not_met", "not_met"), CONTROLS, InherentTier.HIGH, scoring
    )
    assert r.overall == 100.0 and r.band is RiskBand.CRITICAL


def test_subset_and_order_independence(scoring: ScoringSettings) -> None:
    a = score_findings(
        [_f("B-01", "not_met"), _f("A-02", "met")], CONTROLS, InherentTier.MEDIUM, scoring
    )
    b = score_findings(
        [_f("A-02", "met"), _f("B-01", "not_met")], CONTROLS, InherentTier.MEDIUM, scoring
    )
    assert a == b and a.overall == 75.0 and a.band is RiskBand.HIGH  # 3 / 4


def test_errors(scoring: ScoringSettings) -> None:
    with pytest.raises(ConfigError, match="unknown control"):
        score_findings([_f("Z-01", "met")], CONTROLS, InherentTier.LOW, scoring)
    with pytest.raises(ConfigError, match="no findings"):
        score_findings([], CONTROLS, InherentTier.LOW, scoring)


@pytest.mark.parametrize(
    ("score", "band"),
    [(0.0, "low"), (25.0, "low"), (25.1, "medium"), (50.0, "medium"), (50.1, "high"),
     (75.0, "high"), (75.1, "critical"), (100.0, "critical")],
)  # fmt: skip
def test_band_boundaries_are_inclusive_upper_bounds(
    scoring: ScoringSettings, score: float, band: str
) -> None:
    assert band_for(score, scoring.bands) is RiskBand(band)


def test_at_least_keeps_the_more_severe() -> None:
    assert at_least(RiskBand.LOW, RiskBand.HIGH) is RiskBand.HIGH
    assert at_least(RiskBand.CRITICAL, RiskBand.HIGH) is RiskBand.CRITICAL
