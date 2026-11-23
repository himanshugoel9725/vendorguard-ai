"""Golden labels: derived from the specs, complete, and in sync with the committed files."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError
from vendorguard.eval.golden import build_golden, load_golden, write_golden
from vendorguard.eval.specs import SampleState, load_spec
from vendorguard.models.finding import DraftStatus

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]


@pytest.fixture
def control_ids(project_root: Path, settings_override: Callable[..., Settings]) -> list[str]:
    """IDs of the 25 baseline controls."""
    s = settings_override()
    return [c.id for c in load_controls(project_root / s.paths.controls_file).controls]


@pytest.mark.parametrize("stem", STEMS)
def test_each_golden_file_has_all_25_controls(
    stem: str, project_root: Path, control_ids: list[str]
) -> None:
    """Four golden files, each stating a valid status for every control."""
    golden = load_golden(project_root / "data" / "golden" / f"{stem}.json")
    assert sorted(golden.controls) == sorted(control_ids)
    assert len(golden.controls) == 25
    assert golden.stem == stem


@pytest.mark.parametrize("stem", STEMS)
def test_golden_matches_the_spec_with_missing_as_no_evidence(stem: str, project_root: Path) -> None:
    """Every label equals the spec state; ``missing`` is reported as ``no_evidence``."""
    spec = load_spec(project_root / "data" / "samples" / "specs" / f"{stem}.yaml")
    golden = load_golden(project_root / "data" / "golden" / f"{stem}.json")
    assert golden.vendor_id == spec.vendor_id
    assert golden.expected_inherent_tier == spec.expected_inherent_tier
    for control_id, state in spec.controls.items():
        expected = DraftStatus.NO_EVIDENCE if state is SampleState.MISSING else DraftStatus(state)
        assert golden.controls[control_id] is expected
    missing = sum(1 for s in spec.controls.values() if s is SampleState.MISSING)
    assert sum(1 for v in golden.controls.values() if v is DraftStatus.NO_EVIDENCE) == missing


@pytest.mark.parametrize("stem", STEMS)
def test_golden_agrees_with_the_evidence_map(stem: str, project_root: Path) -> None:
    """The evidence JSON next to each sample states the same truth as the golden file."""
    golden = load_golden(project_root / "data" / "golden" / f"{stem}.json")
    evidence = json.loads((project_root / "data" / "samples" / f"{stem}.evidence.json").read_text())
    for control_id, entry in evidence["controls"].items():
        label = "no_evidence" if entry["state"] == "missing" else entry["state"]
        assert golden.controls[control_id].value == label


def test_committed_golden_files_match_a_fresh_generation(
    tmp_path: Path, project_root: Path, control_ids: list[str]
) -> None:
    """If the specs change, `make sample` must be re-run and the golden files committed."""
    written = write_golden(project_root / "data" / "samples" / "specs", tmp_path, control_ids)
    assert [p.stem for p in written] == STEMS
    for path in written:
        committed = project_root / "data" / "golden" / path.name
        assert committed.read_bytes() == path.read_bytes(), f"{path.name} is stale: make sample"


def test_generation_is_deterministic_and_ascii(
    tmp_path: Path, project_root: Path, control_ids: list[str]
) -> None:
    """Two runs write identical bytes, sorted and ASCII-only."""
    specs = project_root / "data" / "samples" / "specs"
    first = [p.read_bytes() for p in write_golden(specs, tmp_path / "a", control_ids)]
    second = [p.read_bytes() for p in write_golden(specs, tmp_path / "b", control_ids)]
    assert first == second
    assert all(b.isascii() and b.endswith(b"\n") for b in first)


def test_write_golden_rejects_an_incomplete_spec(tmp_path: Path, project_root: Path) -> None:
    """A spec that does not cover the control set is a ConfigError, not a partial file."""
    with pytest.raises(ConfigError, match="incomplete"):
        write_golden(project_root / "data" / "samples" / "specs", tmp_path, ["GOV-01", "ZZZ-99"])
    assert not list(tmp_path.glob("*.json"))


def test_load_golden_errors_name_the_file(tmp_path: Path) -> None:
    """Missing, unparsable and invalid files raise ConfigError mentioning the path."""
    with pytest.raises(ConfigError, match="nope.json"):
        load_golden(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError, match="bad.json"):
        load_golden(bad)
    bad.write_text(json.dumps({"vendor_id": "x"}))
    with pytest.raises(ConfigError, match="bad.json"):
        load_golden(bad)


def test_build_golden_sorts_controls(project_root: Path) -> None:
    """Control IDs come out sorted, so files diff cleanly."""
    spec = load_spec(project_root / "data" / "samples" / "specs" / "quillfield.yaml")
    golden = build_golden("quillfield", spec)
    assert list(golden.controls) == sorted(golden.controls)
