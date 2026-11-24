"""Run-folder protection, input validation and failure semantics of ``run_assessment``."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import CollectorRegistry

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError
from vendorguard.models.finding import DraftStatus
from vendorguard.models.run import RunStatus
from vendorguard.observability.audit_log import read_audit_log
from vendorguard.observability.metrics import Metrics
from vendorguard.observability.run_manifest import read_manifest, result_hash
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.pipeline.override import apply_override
from vendorguard.pipeline.run_folder import AUDIT_FILE, prepare_run_dir
from vendorguard.pipeline.run_index import read_result

SAMPLE = Path(__file__).resolve().parents[3] / "data" / "samples" / "quillfield.txt"
Make = Callable[..., Settings]


def _runs(s: Settings) -> list[Path]:
    return list(s.paths.runs_dir.glob("*")) if s.paths.runs_dir.exists() else []


def _stages(run_dir: Path) -> list[str]:
    return [e.stage for e in read_audit_log(run_dir / AUDIT_FILE)]


def _done(metrics: Metrics, status: str) -> float:
    return metrics.registry.get_sample_value("vg_runs_total", {"status": status}) or 0.0


# 1. prepare_run_dir ---------------------------------------------------------------------------


def test_prepare_refuses_a_run_with_overrides_and_deletes_nothing(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    run.mkdir()
    (run / AUDIT_FILE).write_text('{"stage": "analyst_override"}\n', encoding="utf-8")
    (run / "report.md").write_text("keep", encoding="utf-8")
    with pytest.raises(ConfigError, match="overrides"):
        prepare_run_dir(tmp_path, "r1")
    assert (run / "report.md").exists() and (run / AUDIT_FILE).exists()


def test_prepare_refuses_even_when_the_log_is_damaged(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    run.mkdir()
    (run / AUDIT_FILE).write_bytes(b'{broken\n\xff{"stage":"analyst_override"\n')
    with pytest.raises(ConfigError, match="overrides"):
        prepare_run_dir(tmp_path, "r1")
    assert (run / AUDIT_FILE).exists()


def test_prepare_removes_stale_reports_on_a_normal_rerun(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    run.mkdir()
    (run / AUDIT_FILE).write_text('{"stage": "intake"}\n', encoding="utf-8")
    for name in ("report.md", "report.html", "report.json"):
        (run / name).write_text("old", encoding="utf-8")
    (run / "other.txt").write_text("x", encoding="utf-8")
    prepare_run_dir(tmp_path, "r1")
    assert not list(run.glob("report.*")) and not (run / AUDIT_FILE).exists()
    assert (run / "other.txt").exists()


def test_rerun_after_override_is_refused_and_leaves_files_untouched(
    settings_override: Make,
) -> None:
    s = settings_override()
    result = run_assessment(s, "quillfield", [SAMPLE])
    run_dir = s.paths.runs_dir / result.run_id
    controls = load_controls(s.paths.controls_file)
    apply_override(
        s, controls, run_dir, result.findings[0].control_id, DraftStatus.NOT_MET, "r", "a"
    )
    before = {n: (run_dir / n).read_bytes() for n in ("result.json", AUDIT_FILE, "manifest.json")}
    with pytest.raises(ConfigError, match="overrides"):
        run_assessment(s, "quillfield", [SAMPLE])
    assert before == {n: (run_dir / n).read_bytes() for n in before}


# 2. validation --------------------------------------------------------------------------------


@pytest.mark.parametrize("vendor", ["../x", "a b", "", "-x", "x" * 65])
def test_bad_vendor_id_is_refused_before_any_folder(settings_override: Make, vendor: str) -> None:
    s = settings_override()
    with pytest.raises(ConfigError):
        run_assessment(s, vendor, [SAMPLE])
    assert _runs(s) == []


@pytest.mark.parametrize("rid", ["../x", "a b", "", "x" * 65, "a/b"])
def test_bad_run_id_is_refused_before_any_folder(settings_override: Make, rid: str) -> None:
    s = settings_override()
    with pytest.raises(ConfigError):
        run_assessment(s, "quillfield", [SAMPLE], run_id=rid)
    assert _runs(s) == []


def test_an_explicit_valid_run_id_is_used(settings_override: Make) -> None:
    s = settings_override()
    assert run_assessment(s, "quillfield", [SAMPLE], run_id="my-run_1").run_id == "my-run_1"


# 3. failure semantics -------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["render", "memory"])
def test_post_processing_failure_keeps_the_run_done(settings_override: Make, target: str) -> None:
    s = settings_override()
    metrics = Metrics(s.observability, CollectorRegistry())

    def boom(*_: Any) -> None:
        raise RuntimeError("secret detail")

    class Memory:
        def latest_assessment(self, *_: Any, **__: Any) -> None:
            return None

        save_assessment = staticmethod(boom)

    kwargs: dict[str, Any] = {"render": boom} if target == "render" else {"memory": Memory()}
    with pytest.raises(RuntimeError):
        run_assessment(s, "quillfield", [SAMPLE], metrics=metrics, **kwargs)
    (run_dir,) = _runs(s)
    manifest = read_manifest(run_dir / "manifest.json")
    result = read_result(run_dir)
    assert manifest.status is RunStatus.DONE and manifest.result_hash == result_hash(result)
    stages = _stages(run_dir)
    assert "post.failed" in stages and "run.failed" not in stages
    assert "secret detail" not in (run_dir / AUDIT_FILE).read_text(encoding="utf-8")
    assert _done(metrics, "done") == 1 and _done(metrics, "failed") == 0


def test_failure_inside_the_run_marks_it_failed(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_override()
    metrics = Metrics(s.observability, CollectorRegistry())

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr("vendorguard.agents.mapper.MapperAgent.map", boom)
    with pytest.raises(RuntimeError):
        run_assessment(s, "quillfield", [SAMPLE], metrics=metrics)
    (run_dir,) = _runs(s)
    assert read_manifest(run_dir / "manifest.json").status is RunStatus.FAILED
    assert "run.failed" in _stages(run_dir)
    assert _done(metrics, "failed") == 1


def test_keyboard_interrupt_leaves_the_manifest_failed(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_override()

    def stop(*_: Any, **__: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("vendorguard.agents.mapper.MapperAgent.map", stop)
    with pytest.raises(KeyboardInterrupt):
        run_assessment(s, "quillfield", [SAMPLE])
    (run_dir,) = _runs(s)
    assert read_manifest(run_dir / "manifest.json").status is RunStatus.FAILED


def test_fail_never_masks_the_original_error(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_override()
    import vendorguard.pipeline.orchestrator as orch

    real = orch.write_manifest
    calls: list[RunStatus] = []

    def flaky(path: Path, manifest: Any) -> None:
        calls.append(manifest.status)
        if manifest.status is RunStatus.FAILED:
            raise OSError("disk full")
        real(path, manifest)

    def boom(*_: Any, **__: Any) -> None:
        raise ValueError("original")

    monkeypatch.setattr(orch, "write_manifest", flaky)
    monkeypatch.setattr("vendorguard.agents.mapper.MapperAgent.map", boom)
    with pytest.raises(ValueError, match="original"):
        run_assessment(s, "quillfield", [SAMPLE])
    assert RunStatus.FAILED in calls


# 4. override lock and ordering ----------------------------------------------------------------


def test_concurrent_overrides_both_survive(settings_override: Make) -> None:
    s = settings_override()
    result = run_assessment(s, "quillfield", [SAMPLE])
    run_dir = s.paths.runs_dir / result.run_id
    controls = load_controls(s.paths.controls_file)
    ids = [f.control_id for f in result.findings[:2]]
    errors: list[BaseException] = []

    def work(cid: str) -> None:
        try:
            apply_override(s, controls, run_dir, cid, DraftStatus.NOT_MET, "r", "Dana")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(c,)) for c in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert (run_dir / ".lock").exists()
    final = read_result(run_dir)
    assert {f.control_id for f in final.findings if f.override} == set(ids)
    seqs = [e.seq for e in read_audit_log(run_dir / AUDIT_FILE) if e.stage == "analyst_override"]
    assert len(seqs) == 2 and seqs[0] < seqs[1]
    assert read_manifest(run_dir / "manifest.json").result_hash == result_hash(final)


def test_audit_event_comes_after_result_and_manifest_updates(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_override()
    result = run_assessment(s, "quillfield", [SAMPLE])
    run_dir = s.paths.runs_dir / result.run_id
    controls = load_controls(s.paths.controls_file)
    cid = result.findings[0].control_id

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("render failed")

    monkeypatch.setattr("vendorguard.pipeline.override.render_reports", boom)
    with pytest.raises(RuntimeError):
        apply_override(s, controls, run_dir, cid, DraftStatus.NOT_MET, "r", "Dana")
    saved = read_result(run_dir)
    assert next(f for f in saved.findings if f.control_id == cid).override is not None
    assert read_manifest(run_dir / "manifest.json").result_hash == result_hash(saved)
    assert _stages(run_dir).count("analyst_override") == 1
