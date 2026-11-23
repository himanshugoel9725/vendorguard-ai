"""Tests for vendorguard.models.audit."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from vendorguard.models.audit import AuditEvent
from vendorguard.models.decision import Decision, DecisionLabel


def make_event(**kw: object) -> AuditEvent:
    data: dict = {
        "run_id": "r1",
        "seq": 0,
        "ts": datetime(2025, 1, 1, tzinfo=UTC),
        "stage": "triage",
        "actor": "mock",
        "input_hash": "a",
        "output_hash": "b",
        "tokens_in": 0,
        "tokens_out": 0,
        "usd": 0.0,
        "latency_ms": 1.5,
        "cached": False,
    }
    data.update(kw)
    return AuditEvent(**data)


def test_defaults_and_roundtrip() -> None:
    e = make_event()
    assert e.control_id is None
    assert e.decision is None
    assert AuditEvent.model_validate_json(e.model_dump_json()) == e


def test_with_optional_fields_roundtrip() -> None:
    d = Decision(label=DecisionLabel.SUPPORTED, confidence=1.0, provider="citation_check")
    e = make_event(control_id="AC-01", decision=d)
    assert AuditEvent.model_validate_json(e.model_dump_json()) == e


def test_naive_ts_rejected() -> None:
    with pytest.raises(ValidationError):
        make_event(ts=datetime(2025, 1, 1))


@pytest.mark.parametrize("field", ["seq", "tokens_in", "tokens_out"])
def test_negative_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        make_event(**{field: -1})


@pytest.mark.parametrize("field", ["run_id", "stage", "actor"])
def test_empty_required_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        make_event(**{field: ""})


def test_missing_required_extra_frozen() -> None:
    with pytest.raises(ValidationError):
        AuditEvent()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        make_event(bogus=1)
    with pytest.raises(ValidationError):
        make_event().seq = 3  # type: ignore[misc]
