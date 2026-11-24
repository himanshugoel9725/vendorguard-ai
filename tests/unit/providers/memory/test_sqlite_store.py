"""Tests for the SQLite memory store."""

import sqlite3
import threading
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import MemoryStoreError
from vendorguard.models.finding import DraftStatus
from vendorguard.models.run import AssessmentResult
from vendorguard.observability.run_manifest import result_hash
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.pipeline.override import apply_override
from vendorguard.providers.memory.sqlite_store import SqliteMemoryStore

SAMPLE = Path(__file__).resolve().parents[4] / "data" / "samples" / "quillfield.txt"
Make = Callable[..., Settings]


@pytest.fixture
def result(settings_override: Make) -> AssessmentResult:
    return run_assessment(settings_override(), "quillfield", [SAMPLE])


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqliteMemoryStore]:
    s = SqliteMemoryStore(tmp_path / "state" / "memory.db", 5.0)
    yield s
    s.close()


def _later(r: AssessmentResult, run_id: str, minutes: int, **kw: object) -> AssessmentResult:
    return r.model_copy(
        update={"run_id": run_id, "created_at": r.created_at + timedelta(minutes=minutes), **kw}
    )


def test_save_then_load_gives_an_identical_result_and_hash(
    store: SqliteMemoryStore, result: AssessmentResult
) -> None:
    store.save_assessment(result)
    loaded = store.get_assessment(result.run_id)
    assert loaded == result and result_hash(loaded) == result_hash(result)


def test_unknown_run_and_vendor_give_none(store: SqliteMemoryStore) -> None:
    assert store.get_assessment("nope") is None
    assert store.latest_assessment("nobody") is None
    assert store.list_assessments("nobody") == [] and store.list_vendors() == []


def test_latest_is_the_newest_and_can_exclude_a_run(
    store: SqliteMemoryStore, result: AssessmentResult
) -> None:
    old, new = _later(result, "run_old", -60), _later(result, "run_new", 60)
    for r in (new, result, old):
        store.save_assessment(r)
    latest = store.latest_assessment("quillfield")
    assert latest is not None and latest.run_id == "run_new"
    prev = store.latest_assessment("quillfield", exclude_run_id="run_new")
    assert prev is not None and prev.run_id == result.run_id
    assert store.latest_assessment("quillfield", exclude_run_id="x").run_id == "run_new"  # type: ignore[union-attr]


def test_history_is_newest_first_and_vendor_list_counts_runs(
    store: SqliteMemoryStore, result: AssessmentResult
) -> None:
    for r in (result, _later(result, "run_b", 5), _later(result, "run_a", 5)):
        store.save_assessment(r)
    assert [a.run_id for a in store.list_assessments("quillfield")] == [
        "run_b", "run_a", result.run_id,
    ]  # fmt: skip
    (vendor,) = store.list_vendors()
    assert vendor.vendor_id == "quillfield" and vendor.runs == 3
    assert vendor.latest_band is not None and vendor.name == result.profile.vendor_name


def test_saving_the_same_run_again_replaces_it(
    store: SqliteMemoryStore, result: AssessmentResult, tmp_path: Path
) -> None:
    store.save_assessment(result)
    store.save_assessment(result.model_copy(update={"summary": "changed"}))
    got = store.get_assessment(result.run_id)
    assert got is not None and got.summary == "changed"
    db = sqlite3.connect(tmp_path / "state" / "memory.db")
    assert db.execute("SELECT COUNT(*) FROM assessments").fetchone() == (1,)
    assert db.execute("SELECT COUNT(*) FROM findings").fetchone() == (25,)


def test_overrides_are_stored_and_replaced_with_the_result(
    store: SqliteMemoryStore, settings_override: Make, tmp_path: Path
) -> None:
    s = settings_override()
    res = run_assessment(s, "quillfield", [SAMPLE])
    controls = load_controls(s.paths.controls_file)
    run_dir = s.paths.runs_dir / res.run_id
    cid = res.findings[0].control_id
    updated = apply_override(
        s, controls, run_dir, cid, DraftStatus.NOT_MET, "seen", "Dana", memory=store
    )
    db = sqlite3.connect(tmp_path / "state" / "memory.db")
    assert db.execute("SELECT control_id, analyst, new_status FROM overrides").fetchall() == [
        (cid, "Dana", "not_met")
    ]
    assert db.execute(
        "SELECT effective_status FROM findings WHERE control_id = ?", (cid,)
    ).fetchone() == ("not_met",)
    assert store.get_assessment(res.run_id) == updated


def test_awkward_ids_cannot_inject_sql(store: SqliteMemoryStore, result: AssessmentResult) -> None:
    evil = "x'; DROP TABLE vendors; --"
    store.save_assessment(result.model_copy(update={"vendor_id": evil, "run_id": "run_evil"}))
    assert [v.vendor_id for v in store.list_vendors()] == [evil]
    assert store.latest_assessment(evil) is not None and store.get_assessment("' OR 1=1 --") is None


def test_concurrent_saves_all_land(store: SqliteMemoryStore, result: AssessmentResult) -> None:
    runs = [_later(result, f"run_{i:02d}", i) for i in range(12)]
    threads = [threading.Thread(target=store.save_assessment, args=(r,)) for r in runs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.list_assessments("quillfield")) == 12


def test_a_damaged_row_is_a_memory_store_error(
    store: SqliteMemoryStore, result: AssessmentResult, tmp_path: Path
) -> None:
    store.save_assessment(result)
    db = sqlite3.connect(tmp_path / "state" / "memory.db")
    db.execute("UPDATE assessments SET result_json = '{\"x\": 1}'")
    db.commit()
    with pytest.raises(MemoryStoreError, match="damaged"):
        store.get_assessment(result.run_id)


def test_an_unusable_path_is_a_memory_store_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(MemoryStoreError, match="cannot open"):
        SqliteMemoryStore(blocker / "memory.db", 5.0)


def test_the_store_survives_a_reopen(tmp_path: Path, result: AssessmentResult) -> None:
    path = tmp_path / "memory.db"
    first = SqliteMemoryStore(path, 5.0)
    first.save_assessment(result)
    first.close()
    second = SqliteMemoryStore(path, 5.0)
    assert second.get_assessment(result.run_id) == result
    second.close()


def test_user_version_is_set_and_reopen_works(tmp_path: Path) -> None:
    path = tmp_path / "v.db"
    SqliteMemoryStore(path, 5.0).close()
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone() == (1,)
    db.close()
    SqliteMemoryStore(path, 5.0).close()


def test_a_newer_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "v.db"
    SqliteMemoryStore(path, 5.0).close()
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 2")
    db.commit()
    db.close()
    with pytest.raises(MemoryStoreError, match="version 2"):
        SqliteMemoryStore(path, 5.0)


def test_a_version_zero_database_opens_and_is_stamped(
    tmp_path: Path, result: AssessmentResult
) -> None:
    path = tmp_path / "v.db"
    db = sqlite3.connect(path)  # an old database: no pragma was ever set
    db.commit()
    db.close()
    s = SqliteMemoryStore(path, 5.0)
    s.save_assessment(result)
    assert s.get_assessment(result.run_id) == result
    s.close()
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone() == (1,)
    db.close()


def test_resaving_a_run_keeps_its_original_created_at(
    store: SqliteMemoryStore, result: AssessmentResult, tmp_path: Path
) -> None:
    store.save_assessment(result)
    moved = result.model_copy(update={"created_at": result.created_at + timedelta(days=5)})
    store.save_assessment(moved)
    db = sqlite3.connect(tmp_path / "state" / "memory.db")
    (stored,) = db.execute(
        "SELECT created_at FROM assessments WHERE run_id = ?", (result.run_id,)
    ).fetchone()
    db.close()
    assert stored == result.created_at.isoformat()


def test_resaving_an_old_run_does_not_make_it_the_newest(
    store: SqliteMemoryStore, result: AssessmentResult
) -> None:
    old, new = _later(result, "run_old", -60), _later(result, "run_new", 60)
    store.save_assessment(old)
    store.save_assessment(new)
    store.save_assessment(_later(result, "run_old", 120))  # saved again, with a later clock
    assert [a.run_id for a in store.list_assessments("quillfield")] == ["run_new", "run_old"]
    latest = store.latest_assessment("quillfield")
    assert latest is not None and latest.run_id == "run_new"
    (vendor,) = store.list_vendors()
    assert vendor.runs == 2


def test_busy_timeout_setting_exists(settings_override: Make) -> None:
    assert settings_override(memory={"busy_timeout_s": 1.5}).memory.busy_timeout_s == 1.5
