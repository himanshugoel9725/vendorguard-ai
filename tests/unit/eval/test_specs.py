"""The sample-vendor specs: shape, coverage of all controls, plan targets and year-2 diff."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError
from vendorguard.eval.specs import SampleState, VendorSpec, check_covers, load_spec
from vendorguard.models.finding import DraftStatus
from vendorguard.models.vendor import DataCategory

# (met, partial, not_met, missing) targets from docs/PLAN.md task 2.3
TARGETS = {
    "nimbara-hr": (18, 4, 1, 2),
    "quillfield": (12, 6, 3, 4),
    "brightdock": (7, 5, 5, 8),
    "nimbara-hr-y2": (20, 4, 0, 1),
}


@pytest.fixture
def specs(project_root: Path) -> dict[str, VendorSpec]:
    """Every committed spec, keyed by file stem."""
    folder = project_root / "data" / "samples" / "specs"
    return {name: load_spec(folder / f"{name}.yaml") for name in TARGETS}


@pytest.fixture
def control_ids(settings_override: Callable[..., Settings], project_root: Path) -> list[str]:
    """IDs of the 25 baseline controls."""
    path = project_root / settings_override().paths.controls_file
    return [c.id for c in load_controls(path).controls]


def test_there_are_exactly_the_four_planned_specs(project_root: Path) -> None:
    """No spec file is missing or unexpected."""
    found = {p.stem for p in (project_root / "data" / "samples" / "specs").glob("*.yaml")}
    assert found == set(TARGETS)


@pytest.mark.parametrize("name", list(TARGETS))
def test_every_spec_covers_all_25_controls(
    name: str, specs: dict[str, VendorSpec], control_ids: list[str]
) -> None:
    """Each spec states a true status for every control ID, and only for those."""
    assert len(control_ids) == 25
    check_covers(specs[name], control_ids)


@pytest.mark.parametrize("name", list(TARGETS))
def test_state_counts_match_the_plan(name: str, specs: dict[str, VendorSpec]) -> None:
    """Met / partial / not_met / missing counts equal the targets in the plan."""
    counts = specs[name].counts()
    assert tuple(counts[s] for s in SampleState) == TARGETS[name]


def test_year2_differs_from_year1_by_exactly_the_declared_changes(
    specs: dict[str, VendorSpec],
) -> None:
    """Three gaps fixed (partial, not_met, missing) and one new gap, as the spec declares."""
    y1, y2 = specs["nimbara-hr"], specs["nimbara-hr-y2"]
    assert y2.based_on == "nimbara-hr" and y2.vendor_id == y1.vendor_id
    assert y2.report_period != y1.report_period
    changed = {c for c in y1.controls if y1.controls[c] != y2.controls[c]}
    assert y2.changes is not None
    assert changed == set(y2.changes.fixed) | set(y2.changes.new_gaps)
    assert len(y2.changes.fixed) == 3 and len(y2.changes.new_gaps) == 1
    assert {y1.controls[c] for c in y2.changes.fixed} == {
        SampleState.PARTIAL,
        SampleState.NOT_MET,
        SampleState.MISSING,
    }
    assert all(y2.controls[c] is SampleState.MET for c in y2.changes.fixed)
    assert all(y1.controls[c] is SampleState.MET for c in y2.changes.new_gaps)
    assert all(y2.controls[c] is not SampleState.MET for c in y2.changes.new_gaps)


def test_only_quillfield_contains_a_prompt_injection(specs: dict[str, VendorSpec]) -> None:
    """The injection regression paragraph exists once, in a real domain section."""
    with_injection = [n for n, s in specs.items() if s.injection]
    assert with_injection == ["quillfield"]
    injection = specs["quillfield"].injection
    assert injection is not None and injection.section in {
        "GOV",
        "IAM",
        "DAT",
        "OPS",
        "RES",
        "SDL",
        "TPR",
        "PEO",
    }
    assert "ignore all previous instructions" in injection.text.lower()


def test_expected_inherent_tier_follows_the_scoring_rules(
    specs: dict[str, VendorSpec], settings_override: Callable[..., Settings]
) -> None:
    """The ground-truth tier matches the configured high/medium category lists."""
    rules = settings_override().scoring.inherent_risk
    for name, spec in specs.items():
        cats = {c.value for c in spec.data_categories}
        tier = (
            "high"
            if cats & set(rules.high_if_any)
            else "medium"
            if cats & set(rules.medium_if_any)
            else "low"
        )
        assert spec.expected_inherent_tier.value == tier, name
    assert specs["nimbara-hr"].expected_inherent_tier.value == "high"


def test_vendor_facts_agree_with_control_states(specs: dict[str, VendorSpec]) -> None:
    """A vendor with a met certification control lists one; no subprocessor facts without TPR-01."""
    for name, spec in specs.items():
        if spec.controls["TPR-02"] is SampleState.MET:
            assert spec.certifications, name
        if spec.controls["TPR-01"] is SampleState.MISSING:
            assert spec.subprocessors == [], name
        else:
            assert spec.subprocessors, name
        assert DataCategory.NONE not in spec.data_categories or len(spec.data_categories) == 1


def test_missing_state_maps_to_no_evidence() -> None:
    """Golden labels use no_evidence where the document is silent."""
    assert SampleState.MISSING.to_status() is DraftStatus.NO_EVIDENCE
    assert SampleState.NOT_MET.to_status() is DraftStatus.NOT_MET
    assert [s.to_status().value for s in (SampleState.MET, SampleState.PARTIAL)] == [
        "met",
        "partial",
    ]


def test_check_covers_reports_missing_and_unknown_ids(specs: dict[str, VendorSpec]) -> None:
    """An incomplete or padded spec is a ConfigError naming the IDs."""
    spec = specs["brightdock"]
    with pytest.raises(ConfigError, match="missing ZZZ-01"):
        check_covers(spec, [*spec.controls, "ZZZ-01"])
    with pytest.raises(ConfigError, match="unknown PEO-02"):
        check_covers(spec, [c for c in spec.controls if c != "PEO-02"])


def test_load_spec_errors_name_the_file(tmp_path: Path) -> None:
    """Missing file, bad YAML and invalid content all raise ConfigError mentioning the path."""
    with pytest.raises(ConfigError, match="nope.yaml"):
        load_spec(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("vendor_id: x\ncontrols: {GOV-01: sometimes}\n")
    with pytest.raises(ConfigError, match=r"bad.yaml.*controls\.GOV-01"):
        load_spec(bad)
    bad.write_text("a: [unclosed")
    with pytest.raises(ConfigError, match="bad.yaml"):
        load_spec(bad)
