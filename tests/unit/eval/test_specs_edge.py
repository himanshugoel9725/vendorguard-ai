"""Edge cases of eval.specs not covered by test_specs.py."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from vendorguard.errors import ConfigError
from vendorguard.eval.specs import (
    Injection,
    SampleState,
    SpecChanges,
    VendorSpec,
    check_covers,
    load_spec,
)
from vendorguard.models.finding import DraftStatus


@pytest.fixture
def raw(project_root: Path) -> dict[str, Any]:
    path = project_root / "data" / "samples" / "specs" / "nimbara-hr.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def spec(project_root: Path) -> VendorSpec:
    return load_spec(project_root / "data" / "samples" / "specs" / "nimbara-hr.yaml")


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "broken-spec.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_check_covers_exact_match_passes_silently(spec: VendorSpec) -> None:
    assert check_covers(spec, list(spec.controls)) is None


def test_load_spec_valid_roundtrip(tmp_path: Path, raw: dict[str, Any]) -> None:
    assert load_spec(_write(tmp_path, raw)).vendor_id == raw["vendor_id"]


def test_load_spec_unknown_field(tmp_path: Path, raw: dict[str, Any]) -> None:
    raw["bogus"] = 1
    with pytest.raises(ConfigError, match=r"broken-spec\.yaml.*bogus"):
        load_spec(_write(tmp_path, raw))


def test_load_spec_bad_state_value(tmp_path: Path, raw: dict[str, Any]) -> None:
    raw["controls"]["GOV-01"] = "maybe"
    with pytest.raises(ConfigError, match=r"broken-spec\.yaml.*controls\.GOV-01"):
        load_spec(_write(tmp_path, raw))


def test_load_spec_bad_data_category(tmp_path: Path, raw: dict[str, Any]) -> None:
    raw["data_categories"] = ["not_a_category"]
    with pytest.raises(ConfigError, match=r"broken-spec\.yaml.*data_categories"):
        load_spec(_write(tmp_path, raw))


def test_load_spec_empty_service_item(tmp_path: Path, raw: dict[str, Any]) -> None:
    raw["services"] = ["payroll", ""]
    with pytest.raises(ConfigError, match=r"broken-spec\.yaml.*services\.1"):
        load_spec(_write(tmp_path, raw))


def test_load_spec_missing_controls(tmp_path: Path, raw: dict[str, Any]) -> None:
    del raw["controls"]
    with pytest.raises(ConfigError, match=r"broken-spec\.yaml.*controls"):
        load_spec(_write(tmp_path, raw))


def test_load_spec_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty.yaml"):
        load_spec(path)


def test_counts_always_has_all_four_states(spec: VendorSpec) -> None:
    only_met = spec.model_copy(update={"controls": {"GOV-01": SampleState.MET}})
    assert only_met.counts() == {
        SampleState.MET: 1,
        SampleState.PARTIAL: 0,
        SampleState.NOT_MET: 0,
        SampleState.MISSING: 0,
    }
    empty = spec.model_copy(update={"controls": {}})
    assert set(empty.counts()) == set(SampleState)
    assert sum(empty.counts().values()) == 0


@pytest.mark.parametrize(
    ("state", "status"),
    [
        (SampleState.MET, DraftStatus.MET),
        (SampleState.PARTIAL, DraftStatus.PARTIAL),
        (SampleState.NOT_MET, DraftStatus.NOT_MET),
        (SampleState.MISSING, DraftStatus.NO_EVIDENCE),
    ],
)
def test_to_status_all_states(state: SampleState, status: DraftStatus) -> None:
    assert state.to_status() is status


@pytest.mark.parametrize("bad", [""])
def test_injection_rejects_empty_text_or_section(bad: str) -> None:
    with pytest.raises(ValidationError):
        Injection(section=bad, text="x")
    with pytest.raises(ValidationError):
        Injection(section="GOV", text=bad)


def test_spec_changes_requires_both_lists() -> None:
    assert SpecChanges(fixed=[], new_gaps=[]).fixed == []
    with pytest.raises(ValidationError):
        SpecChanges.model_validate({"fixed": []})


def test_vendor_spec_is_frozen(spec: VendorSpec) -> None:
    with pytest.raises(ValidationError):
        spec.vendor_id = "other"  # type: ignore[misc]
