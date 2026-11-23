"""Tests for vendorguard.models.vendor."""

import pytest
from pydantic import ValidationError

from vendorguard.models.vendor import MAX_ITEMS, MAX_TEXT_CHARS, DataCategory, VendorProfile

LIST_FIELDS = ["services", "data_categories", "hosting", "certifications", "subprocessors"]


def make_profile(**kw: object) -> VendorProfile:
    data: dict = {
        "vendor_name": "Acme",
        "services": ["crm"],
        "data_categories": [DataCategory.PII],
        "hosting": ["aws"],
        "certifications": ["SOC 2"],
        "subprocessors": [],
    }
    data.update(kw)
    return VendorProfile(**data)


def test_data_category_values() -> None:
    assert {c.name: c.value for c in DataCategory} == {
        "PII": "pii",
        "FINANCIAL": "financial",
        "HEALTH": "health",
        "CREDENTIALS": "credentials",
        "CUSTOMER_CONTENT": "customer_content",
        "NONE": "none",
    }


def test_roundtrip_and_optional_period() -> None:
    p = make_profile()
    assert p.report_period is None
    assert VendorProfile.model_validate_json(p.model_dump_json()) == p
    assert make_profile(report_period="2024").report_period == "2024"


def test_text_bounds() -> None:
    assert make_profile(vendor_name="x" * MAX_TEXT_CHARS)
    with pytest.raises(ValidationError):
        make_profile(vendor_name="x" * (MAX_TEXT_CHARS + 1))
    with pytest.raises(ValidationError):
        make_profile(vendor_name="")
    with pytest.raises(ValidationError):
        make_profile(report_period="")
    with pytest.raises(ValidationError):
        make_profile(services=["y" * (MAX_TEXT_CHARS + 1)])
    assert make_profile(vendor_name="é" * MAX_TEXT_CHARS)


@pytest.mark.parametrize("field", ["services", "hosting", "certifications", "subprocessors"])
def test_list_bounds(field: str) -> None:
    assert make_profile(**{field: ["a"] * MAX_ITEMS})
    with pytest.raises(ValidationError):
        make_profile(**{field: ["a"] * (MAX_ITEMS + 1)})


def test_data_categories_bound() -> None:
    n = len(DataCategory)
    assert make_profile(data_categories=list(DataCategory))
    with pytest.raises(ValidationError):
        make_profile(data_categories=list(DataCategory) + [DataCategory.PII])
    assert n < MAX_ITEMS + 1


def test_invalid_category_and_extra() -> None:
    with pytest.raises(ValidationError):
        make_profile(data_categories=["bogus"])
    with pytest.raises(ValidationError):
        make_profile(bogus=1)


def test_frozen() -> None:
    with pytest.raises(ValidationError):
        make_profile().vendor_name = "x"  # type: ignore[misc]


def test_json_schema() -> None:
    schema = VendorProfile.model_json_schema()
    assert set(schema["properties"]) == set(VendorProfile.model_fields)
    for f in LIST_FIELDS:
        assert "maxItems" in schema["properties"][f]
