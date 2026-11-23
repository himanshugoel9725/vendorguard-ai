"""Tests for the shared contract base and constrained types."""

import pytest
from pydantic import TypeAdapter, ValidationError

from vendorguard.models._base import (
    ContractModel,
    NonEmptyStr,
    NonNegInt,
    Probability,
    Score100,
    Sha256,
)


class _Sample(ContractModel):
    name: str


def test_frozen() -> None:
    m = _Sample(name="a")
    with pytest.raises(ValidationError):
        m.name = "b"  # type: ignore[misc]


def test_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        _Sample(name="a", other=1)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("tp", "good", "bad"),
    [
        (Probability, [0.0, 1.0, 0.5], [-0.01, 1.01]),
        (Score100, [0.0, 100.0], [-0.1, 100.1]),
        (NonNegInt, [0, 5], [-1]),
        (NonEmptyStr, ["x", "é"], [""]),
        (Sha256, ["a" * 64, "0" * 64], ["A" * 64, "a" * 63, "a" * 65, "g" * 64, ""]),
    ],
)
def test_constrained_types(tp: object, good: list, bad: list) -> None:
    ta = TypeAdapter(tp)
    for v in good:
        assert ta.validate_python(v) == v
    for v in bad:
        with pytest.raises(ValidationError):
            ta.validate_python(v)


@pytest.mark.parametrize("value", ["", " ", "\t\n  ", "\u00a0"])
def test_non_empty_str_rejects_empty_and_blank(value: str) -> None:
    """NonEmptyStr needs at least one non-whitespace character."""
    adapter = TypeAdapter(NonEmptyStr)
    with pytest.raises(ValidationError):
        adapter.validate_python(value)


@pytest.mark.parametrize("value", ["a", " a ", "a b", "\n x", "e\u0301"])
def test_non_empty_str_accepts_text_and_keeps_it_unchanged(value: str) -> None:
    """Surrounding whitespace is allowed and the value is not stripped."""
    assert TypeAdapter(NonEmptyStr).validate_python(value) == value
