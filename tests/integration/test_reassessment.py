"""nimbara-hr (year 1) then nimbara-hr-y2 (year 2) for the same vendor, with the mock pipeline."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.eval.specs import load_spec
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.providers.memory.sqlite_store import SqliteMemoryStore

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
Make = Callable[..., Settings]


@pytest.fixture
def two_runs(settings_override: Make, tmp_path: Path):  # type: ignore[no-untyped-def]
    s = settings_override()
    store = SqliteMemoryStore(tmp_path / "mem.db")
    first = run_assessment(s, "nimbara-hr", [SAMPLES / "nimbara-hr.pdf"], memory=store)
    second = run_assessment(s, "nimbara-hr", [SAMPLES / "nimbara-hr-y2.pdf"], memory=store)
    yield s, store, first, second
    store.close()


def test_the_first_run_has_no_diff(two_runs) -> None:  # type: ignore[no-untyped-def]
    _, _, first, _ = two_runs
    assert first.diff is None


def test_year_two_shows_exactly_the_specs_fixes_and_new_gap(two_runs) -> None:  # type: ignore[no-untyped-def]
    _, _, first, second = two_runs
    changes = load_spec(SAMPLES / "specs" / "nimbara-hr-y2.yaml").changes
    assert changes is not None
    assert second.diff is not None and second.diff.previous_run_id == first.run_id
    assert second.diff.resolved_gaps == sorted(changes.fixed)
    assert second.diff.new_gaps == sorted(changes.new_gaps)
    assert {c.control_id for c in second.diff.changed} == set(changes.fixed) | set(changes.new_gaps)
    assert second.diff.score_delta == round(second.score.overall - first.score.overall, 1)
    assert second.diff.score_delta < 0  # three gaps fixed, one opened: the risk went down


def test_the_diff_is_in_the_reports_and_the_summary_facts(two_runs) -> None:  # type: ignore[no-untyped-def]
    s, _, first, second = two_runs
    run_dir = s.paths.runs_dir / second.run_id
    md = (run_dir / "report.md").read_text(encoding="utf-8")
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    for cid in ("IAM-04", "RES-03", "PEO-02", "OPS-02"):
        assert cid in md and cid in html
    assert "Changes since the previous assessment" in md
    assert first.run_id.replace("_", "\\_") in md


def test_memory_holds_both_runs_and_a_rerun_does_not_diff_against_itself(two_runs) -> None:  # type: ignore[no-untyped-def]
    s, store, first, second = two_runs
    ids = {a.run_id for a in store.list_assessments("nimbara-hr")}
    assert ids == {first.run_id, second.run_id}
    again = run_assessment(s, "nimbara-hr", [SAMPLES / "nimbara-hr-y2.pdf"], memory=store)
    assert again.run_id == second.run_id and again.diff is not None
    assert again.diff.previous_run_id == first.run_id  # the run being replaced is excluded
