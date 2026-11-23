"""Tests for vendorguard.models.score."""

import pytest
from pydantic import ValidationError

from vendorguard.models.score import InherentRisk, InherentTier, RiskBand, RiskScore


def make_score(**kw: object) -> RiskScore:
    data: dict = {
        "overall": 42.5,
        "band": RiskBand.MEDIUM,
        "domain_scores": {"AC": 10.0, "BC": 100.0},
        "triggered_rules": ["rule"],
    }
    data.update(kw)
    return RiskScore(**data)


def test_enums() -> None:
    assert [t.value for t in InherentTier] == ["low", "medium", "high"]
    assert [b.value for b in RiskBand] == ["low", "medium", "high", "critical"]


def test_roundtrip() -> None:
    s = make_score()
    assert RiskScore.model_validate_json(s.model_dump_json()) == s
    r = InherentRisk(tier=InherentTier.HIGH, reasons=["pii"])
    assert InherentRisk.model_validate_json(r.model_dump_json()) == r


@pytest.mark.parametrize("v", [0, 100, 0.0, 100.0])
def test_overall_ok(v: float) -> None:
    assert make_score(overall=v).overall == v


@pytest.mark.parametrize("v", [-0.1, 100.1])
def test_overall_rejected(v: float) -> None:
    with pytest.raises(ValidationError):
        make_score(overall=v)


@pytest.mark.parametrize("v", [-1.0, 101.0])
def test_domain_scores_rejected(v: float) -> None:
    with pytest.raises(ValidationError):
        make_score(domain_scores={"AC": v})


def test_frozen_extra() -> None:
    with pytest.raises(ValidationError):
        make_score().overall = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        make_score(bogus=1)
    with pytest.raises(ValidationError):
        InherentRisk(tier="extreme", reasons=[])
