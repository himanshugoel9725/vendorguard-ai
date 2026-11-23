"""load_controls: the real baseline set and every broken-file error path."""

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from random import Random
from typing import Any

import pytest
import yaml

from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError

Mutator = Callable[[dict[str, Any]], None]


@pytest.fixture
def baseline(project_root: Path) -> Path:
    return project_root / "config" / "controls" / "baseline_v1.yaml"


@pytest.fixture
def raw(baseline: Path) -> dict[str, Any]:
    data = yaml.safe_load(baseline.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def write(tmp_path: Path) -> Callable[[Any], Path]:
    def _write(data: Any) -> Path:
        path = tmp_path / "controls.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    return _write


def _index(raw: dict[str, Any], control_id: str) -> int:
    return next(i for i, c in enumerate(raw["controls"]) if c["id"] == control_id)


def test_baseline_loads_with_expected_shape(baseline: Path) -> None:
    cs = load_controls(baseline)
    ids = [c.id for c in cs.controls]
    assert cs.version == "baseline_v1"
    assert cs.description
    assert len(ids) == 25 and ids == sorted(ids)
    assert len(cs.domains) == 8
    by_domain = Counter(c.domain for c in cs.controls)
    assert dict(by_domain) == {
        "GOV": 3,
        "IAM": 4,
        "DAT": 5,
        "OPS": 4,
        "RES": 3,
        "SDL": 2,
        "TPR": 2,
        "PEO": 2,
    }
    by_crit = Counter(c.criticality.value for c in cs.controls)
    assert dict(by_crit) == {"critical": 4, "high": 11, "medium": 9, "low": 1}


def test_every_control_has_keywords_and_mappings(baseline: Path) -> None:
    for c in load_controls(baseline).controls:
        assert len(c.keywords) == 6, c.id
        assert c.iso27001 and c.nist_csf, c.id


def test_loading_is_deterministic(baseline: Path) -> None:
    assert load_controls(baseline) == load_controls(baseline)


def test_shuffled_file_still_loads_sorted(
    raw: dict[str, Any], write: Callable[[Any], Path]
) -> None:
    Random(3).shuffle(raw["controls"])  # noqa: S311
    assert [c["id"] for c in raw["controls"]] != sorted(c["id"] for c in raw["controls"])
    ids = [c.id for c in load_controls(write(raw)).controls]
    assert ids == sorted(ids) and len(ids) == 25


def test_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "absent.yaml"
    with pytest.raises(ConfigError, match="absent.yaml"):
        load_controls(path)


def test_malformed_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("controls: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="bad.yaml"):
        load_controls(path)


def test_top_level_list_is_rejected(write: Callable[[Any], Path]) -> None:
    path = write(["a", "b"])
    with pytest.raises(ConfigError, match="controls.yaml.*mapping"):
        load_controls(path)


def test_duplicate_id(raw: dict[str, Any], write: Callable[[Any], Path]) -> None:
    raw["controls"].append(dict(raw["controls"][0]))
    path = write(raw)
    with pytest.raises(ConfigError, match=r"(?s)controls\.yaml.*duplicate control ids: GOV-01"):
        load_controls(path)


def test_domain_missing_from_domains_mentions_unknown_domains(
    raw: dict[str, Any], write: Callable[[Any], Path]
) -> None:
    del raw["domains"]["PEO"]
    with pytest.raises(ConfigError, match=r"(?s)controls\.yaml.*unknown domains: PEO"):
        load_controls(write(raw))


def test_domain_not_matching_id_prefix(raw: dict[str, Any], write: Callable[[Any], Path]) -> None:
    raw["domains"]["ZZZ"] = "Other"
    i = _index(raw, "IAM-02")
    raw["controls"][i]["domain"] = "ZZZ"
    with pytest.raises(ConfigError) as err:
        load_controls(write(raw))
    msg = str(err.value)
    assert "controls.yaml" in msg
    assert f"controls[{i}] (IAM-02)" in msg
    assert "must start with its domain" in msg


def test_id_not_starting_with_domain_code(
    raw: dict[str, Any], write: Callable[[Any], Path]
) -> None:
    i = _index(raw, "OPS-01")
    raw["controls"][i]["id"] = "XYZ-01"
    with pytest.raises(
        ConfigError, match=r"(?s)controls\.yaml.*XYZ-01.*must start with its domain"
    ):
        load_controls(write(raw))


def test_empty_keywords_list(raw: dict[str, Any], write: Callable[[Any], Path]) -> None:
    i = _index(raw, "IAM-02")
    raw["controls"][i]["keywords"] = []
    with pytest.raises(
        ConfigError, match=rf"(?s)controls\.yaml.*controls\[{i}\] \(IAM-02\)\.keywords"
    ):
        load_controls(write(raw))


def test_blank_keyword(raw: dict[str, Any], write: Callable[[Any], Path]) -> None:
    i = _index(raw, "IAM-02")
    raw["controls"][i]["keywords"][2] = ""
    with pytest.raises(ConfigError, match=rf"controls\[{i}\] \(IAM-02\)\.keywords\.2"):
        load_controls(write(raw))


def test_invalid_criticality_does_not_echo_value(
    raw: dict[str, Any], write: Callable[[Any], Path]
) -> None:
    i = _index(raw, "DAT-01")
    raw["controls"][i]["criticality"] = "supercalifragilistic"
    with pytest.raises(ConfigError) as err:
        load_controls(write(raw))
    msg = str(err.value)
    assert f"controls[{i}] (DAT-01).criticality" in msg
    assert "supercalifragilistic" not in msg


def test_missing_required_field(raw: dict[str, Any], write: Callable[[Any], Path]) -> None:
    i = _index(raw, "RES-02")
    del raw["controls"][i]["met_criteria"]
    with pytest.raises(ConfigError) as err:
        load_controls(write(raw))
    assert str(err.value).endswith(f"controls[{i}] (RES-02).met_criteria: missing")


def test_unknown_extra_field_on_control(raw: dict[str, Any], write: Callable[[Any], Path]) -> None:
    i = _index(raw, "SDL-01")
    raw["controls"][i]["surprise"] = "hunter2-secret"
    with pytest.raises(ConfigError) as err:
        load_controls(write(raw))
    msg = str(err.value)
    assert f"controls[{i}] (SDL-01).surprise" in msg
    assert "hunter2-secret" not in msg


def test_missing_top_level_field(raw: dict[str, Any], write: Callable[[Any], Path]) -> None:
    del raw["version"]
    with pytest.raises(ConfigError, match=r"(?s)controls\.yaml.*version: missing"):
        load_controls(write(raw))


def test_subset_is_sorted_and_leaves_original_untouched(baseline: Path) -> None:
    cs = load_controls(baseline)
    sub = cs.subset(["TPR-01", "GOV-02"])
    assert [c.id for c in sub.controls] == ["GOV-02", "TPR-01"]
    assert len(cs.controls) == 25
    assert cs.subset([]).controls == []
    with pytest.raises(ConfigError, match="NOPE-99"):
        cs.subset(["NOPE-99"])
