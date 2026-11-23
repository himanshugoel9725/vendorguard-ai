"""Tests for vendorguard.models.control."""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from vendorguard.errors import ConfigError
from vendorguard.models.control import Control, ControlSet, Criticality


def make_control(cid: str = "AC-01", domain: str = "AC", **kw: object) -> Control:
    data: dict = {
        "id": cid,
        "title": "t",
        "domain": domain,
        "criticality": Criticality.HIGH,
        "iso27001": ["A.5"],
        "nist_csf": ["PR.AC"],
        "requirement": "r",
        "met_criteria": "m",
        "keywords": ["mfa"],
    }
    data.update(kw)
    return Control(**data)


def make_set(**kw: object) -> ControlSet:
    data: dict = {
        "version": "1",
        "name": "n",
        "domains": {"AC": "Access", "BC": "Continuity"},
        "controls": [make_control("BC-01", "BC"), make_control("AC-02"), make_control("AC-01")],
    }
    data.update(kw)
    return ControlSet(**data)


def test_criticality_values() -> None:
    assert [c.value for c in Criticality] == ["low", "medium", "high", "critical"]


def test_roundtrip() -> None:
    cs = make_set()
    assert ControlSet.model_validate_json(cs.model_dump_json()) == cs


@pytest.mark.parametrize(
    "kw",
    [
        {"id": "BC-01"},
        {"id": "AC01"},
        {"keywords": []},
        {"keywords": [""]},
        {"keywords": ["ok", ""]},
        {"bogus": 1},
    ],
)
def test_control_rejects(kw: dict) -> None:
    with pytest.raises(ValidationError):
        make_control(**kw)


@pytest.mark.parametrize("blank", ["   ", "\t\n", "\u00a0"])
def test_control_blank_keyword_whitespace_only(blank: str) -> None:
    """Keywords need at least one non-blank item: whitespace-only strings are rejected."""
    with pytest.raises(ValidationError):
        make_control(keywords=[blank])


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="AC-01"):
        make_set(controls=[make_control("AC-01"), make_control("AC-01")])


def test_unknown_domain_rejected() -> None:
    with pytest.raises(ValidationError, match="ZZ"):
        make_set(controls=[make_control("ZZ-01", "ZZ")])


def test_description_optional() -> None:
    assert make_set().description == ""


def test_subset_sorted_and_original_untouched() -> None:
    cs = make_set()
    sub = cs.subset(["BC-01", "AC-01"])
    assert [c.id for c in sub.controls] == ["AC-01", "BC-01"]
    assert len(cs.controls) == 3
    assert [c.id for c in cs.controls][0] == "BC-01"


def test_subset_empty_and_iterables() -> None:
    cs = make_set()
    assert cs.subset([]).controls == []
    assert [c.id for c in cs.subset({"AC-02"}).controls] == ["AC-02"]
    gen: Iterator[str] = (i for i in ("AC-02", "AC-01"))
    assert [c.id for c in cs.subset(gen).controls] == ["AC-01", "AC-02"]


def test_subset_unknown_raises() -> None:
    with pytest.raises(ConfigError, match="NOPE-9"):
        make_set().subset(["AC-01", "NOPE-9"])


def test_subset_deterministic() -> None:
    cs = make_set()
    assert cs.subset(["AC-01", "AC-02"]) == cs.subset(["AC-02", "AC-01"])
