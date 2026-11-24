"""End-to-end runs of the pipeline on the synthetic samples with the mock LLM (offline)."""

from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.errors import BudgetExceededError, ConfigError
from vendorguard.eval.golden import load_golden
from vendorguard.factory import build_providers
from vendorguard.models.run import RunStatus
from vendorguard.observability.audit_log import read_audit_log
from vendorguard.observability.metrics import Metrics
from vendorguard.observability.run_manifest import read_manifest, result_hash
from vendorguard.pipeline import orchestrator
from vendorguard.pipeline.orchestrator import run_assessment

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "samples" / "quillfield.txt"
GOLDEN = ROOT / "data" / "golden" / "quillfield.json"
Make = Callable[..., Settings]


def test_quillfield_run_completes_with_one_cascade_trace_per_control(
    settings_override: Make,
) -> None:
    s = settings_override()
    result = run_assessment(s, "quillfield", [SAMPLE])
    run_dir = s.paths.runs_dir / result.run_id
    assert (run_dir / "result.json").is_file()
    events = read_audit_log(run_dir / "audit.jsonl")
    stages = Counter(e.stage for e in events)
    assert stages["cascade.finding"] == len(result.findings) == 25
    for finding in result.findings:
        gates = [
            e for e in events if e.control_id == finding.control_id and e.stage.startswith("gate.")
        ]
        assert len(gates) == len(finding.trace)
    assert [f.control_id for f in result.findings] == sorted(f.control_id for f in result.findings)
    manifest = read_manifest(run_dir / "manifest.json")
    assert manifest.status is RunStatus.DONE and manifest.result_hash == result_hash(result)
    assert set(manifest.prompt_hashes) == {"intake", "mapper", "reviewer", "reporter"}
    assert manifest.inputs[0].filename == "quillfield.txt"


def test_findings_agree_with_the_golden_labels(settings_override: Make) -> None:
    result = run_assessment(settings_override(), "quillfield", [SAMPLE])
    golden = load_golden(GOLDEN).controls
    hits = sum(f.status.value == golden[f.control_id] for f in result.findings)
    assert hits / len(result.findings) >= 0.85


def test_controls_subset_scores_only_those_controls(settings_override: Make) -> None:
    s = settings_override(pipeline={"controls_subset": ["IAM-02", "DAT-01"]})
    result = run_assessment(s, "quillfield", [SAMPLE])
    assert [f.control_id for f in result.findings] == ["DAT-01", "IAM-02"]


def test_result_hash_is_stable_across_runs_and_concurrency(settings_override: Make) -> None:
    one = run_assessment(settings_override(pipeline={"max_concurrency": 1}), "quillfield", [SAMPLE])
    four = run_assessment(
        settings_override(pipeline={"max_concurrency": 4}), "quillfield", [SAMPLE]
    )
    again = run_assessment(
        settings_override(pipeline={"max_concurrency": 1}), "quillfield", [SAMPLE]
    )
    assert one.run_id == four.run_id == again.run_id
    assert result_hash(one) == result_hash(four) == result_hash(again)


def test_rerun_with_the_same_id_does_not_double_the_audit_log(settings_override: Make) -> None:
    s = settings_override()
    first = run_assessment(s, "quillfield", [SAMPLE])
    run_assessment(s, "quillfield", [SAMPLE])
    events = read_audit_log(s.paths.runs_dir / first.run_id / "audit.jsonl")
    assert Counter(e.stage for e in events)["cascade.finding"] == 25
    assert events[0].seq == 0


def test_a_failing_stage_writes_a_failed_manifest_and_closes_providers(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings_override()
    closed: list[str] = []
    real = orchestrator.build_providers

    def build(settings: Settings):  # type: ignore[no-untyped-def]
        prov = real(settings)
        return type(prov)(
            llm=prov.llm, embedder=prov.embedder, cache=prov.cache, tracker=prov.tracker,
            closers=(lambda: closed.append("closed"),),
        )  # fmt: skip

    def boom(*_a: object, **_k: object) -> None:
        raise BudgetExceededError("stop")

    monkeypatch.setattr(orchestrator, "build_providers", build)
    monkeypatch.setattr("vendorguard.agents.mapper.MapperAgent.map", boom)
    metrics = Metrics(s.observability)
    with pytest.raises(BudgetExceededError):
        run_assessment(s, "quillfield", [SAMPLE], metrics=metrics)
    (run_dir,) = list(s.paths.runs_dir.iterdir())
    manifest = read_manifest(run_dir / "manifest.json")
    assert manifest.status is RunStatus.FAILED and manifest.result_hash is None
    assert "run.failed" in {e.stage for e in read_audit_log(run_dir / "audit.jsonl")}
    assert not (run_dir / "result.json").exists()
    assert closed == ["closed"]
    assert b'vg_runs_total{status="failed"} 1.0' in metrics.render()


def test_providers_given_by_the_caller_are_not_closed(settings_override: Make) -> None:
    s = settings_override()
    closed: list[str] = []
    prov = build_providers(s)
    prov = type(prov)(
        llm=prov.llm, embedder=prov.embedder, cache=prov.cache, tracker=prov.tracker,
        closers=(lambda: closed.append("closed"),),
    )  # fmt: skip
    run_assessment(s, "quillfield", [SAMPLE], providers=prov)
    assert closed == []


@pytest.mark.parametrize(
    ("vendor", "paths"), [("", [SAMPLE]), ("  ", [SAMPLE]), ("quillfield", [])]
)
def test_bad_input_raises_before_any_run_folder(
    settings_override: Make, vendor: str, paths: list[Path]
) -> None:
    s = settings_override()
    with pytest.raises(ConfigError):
        run_assessment(s, vendor, paths)
    assert not s.paths.runs_dir.exists() or not list(s.paths.runs_dir.iterdir())


def test_hooks_and_memory_are_used_when_given(settings_override: Make) -> None:
    s = settings_override()
    rendered: list[Path] = []
    saved: list[str] = []

    class Memory:
        def list_assessments(self, vendor_id: str):  # type: ignore[no-untyped-def]
            return []

        def latest_assessment(self, vendor_id: str, *, exclude_run_id: str | None = None):  # type: ignore[no-untyped-def]
            return None

        def save_assessment(self, result) -> None:  # type: ignore[no-untyped-def]
            saved.append(result.run_id)

    result = run_assessment(
        s,
        "quillfield",
        [SAMPLE],
        memory=Memory(),
        render=lambda r, d: rendered.append(d),  # type: ignore[arg-type]
    )
    assert saved == [result.run_id] and rendered == [s.paths.runs_dir / result.run_id]
    assert result.diff is None
