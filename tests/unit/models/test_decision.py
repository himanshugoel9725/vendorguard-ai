"""Tests for vendorguard.models.decision."""

import pytest
from pydantic import ValidationError

from vendorguard.models.decision import Decision, DecisionLabel, Gate, GateTrace


def make_decision(**kw: object) -> Decision:
    data: dict = {"label": DecisionLabel.ADDRESSED, "confidence": 0.8, "provider": "mock"}
    data.update(kw)
    return Decision(**data)


def test_enum_values() -> None:
    assert [d.value for d in DecisionLabel] == [
        "addressed",
        "not_addressed",
        "supported",
        "unsupported",
    ]
    assert [g.value for g in Gate] == ["triage", "citation", "verify", "review"]


def test_defaults_and_roundtrip() -> None:
    d = make_decision()
    assert d.fallback_used is False
    assert d.reason is None
    assert Decision.model_validate_json(d.model_dump_json()) == d


@pytest.mark.parametrize("c", [0, 1, 0.0, 1.0])
def test_confidence_ok(c: float) -> None:
    assert make_decision(confidence=c).confidence == c


@pytest.mark.parametrize("c", [-0.01, 1.01])
def test_confidence_rejected(c: float) -> None:
    with pytest.raises(ValidationError):
        make_decision(confidence=c)


def test_decision_rejects_bad_input() -> None:
    with pytest.raises(ValidationError):
        make_decision(provider="")
    with pytest.raises(ValidationError):
        make_decision(label="maybe")
    with pytest.raises(ValidationError):
        make_decision(bogus=1)
    with pytest.raises(ValidationError):
        make_decision().confidence = 0.1  # type: ignore[misc]


def test_gate_trace() -> None:
    t = GateTrace(gate=Gate.TRIAGE, decision=make_decision(), round=0)
    assert GateTrace.model_validate_json(t.model_dump_json()) == t
    with pytest.raises(ValidationError):
        GateTrace(gate=Gate.TRIAGE, decision=make_decision(), round=-1)
    with pytest.raises(ValidationError):
        GateTrace(decision=make_decision(), round=0)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        GateTrace(gate=Gate.TRIAGE, round=0)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        GateTrace(gate=Gate.TRIAGE, decision=make_decision())  # type: ignore[call-arg]
