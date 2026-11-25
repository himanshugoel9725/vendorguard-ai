"""Eval runner: config isolation, skipping, recording failures, results file (mock only)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from vendorguard.cli.main import app
from vendorguard.config import Settings
from vendorguard.config_models.core import EvalConfig
from vendorguard.eval import runner
from vendorguard.eval.results import Outcome, RunRecord, aggregate
from vendorguard.eval.results_io import write_results
from vendorguard.eval.runner import (
    config_settings,
    run_config,
    run_eval,
    sample_stems,
    skip_reason,
)

Make = Callable[..., Settings]
MOCK = EvalConfig(name="mock-rule", llm="mock", decider="rule", embeddings="none")


@pytest.fixture
def s(settings_override: Make, tmp_path: Path) -> Settings:
    return settings_override(
        eval={
            "work_dir": tmp_path / "eval",
            "results_dir": tmp_path / "results",
            "configs": [
                MOCK.model_dump(),
                {**MOCK.model_dump(), "name": "mock-judge", "decider": "llm_judge"},
            ],
        }
    )


def test_sample_stems_are_the_four_vendors(s: Settings) -> None:
    assert sample_stems(s) == ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]


def test_config_settings_isolates_paths_and_sets_providers(s: Settings) -> None:
    cfg = EvalConfig(name="x", llm="mock", decider="llm_judge", embeddings="none")
    local = config_settings(s, cfg)
    assert local.decision.provider == "llm_judge"
    assert local.paths.runs_dir == s.eval.work_dir / "x" / "runs"
    assert local.cache.sqlite_path == s.eval.work_dir / "x" / "state" / "cache.db"
    assert local.cache.enabled is s.eval.cache_enabled
    assert s.decision.provider == "rule"  # the original is untouched


def test_skip_reason_for_missing_keys(s: Settings) -> None:
    jev = EvalConfig(name="j", llm="mock", decider="jev", embeddings="none")
    assert "Jev" in (skip_reason(s, jev) or "")
    hosted = EvalConfig(name="h", llm="openai", decider="rule", embeddings="none")
    assert "llm.openai" in (skip_reason(s, hosted) or "")
    assert skip_reason(s, MOCK) is None
    keyed = s.model_copy(
        update={
            "decision": s.decision.model_copy(
                update={"jev": s.decision.jev.model_copy(update={"api_key": SecretStr("k" * 20)})}
            )
        }
    )
    assert skip_reason(keyed, jev) is None


def test_skipped_config_runs_nothing(s: Settings) -> None:
    jev = EvalConfig(name="j", llm="mock", decider="jev", embeddings="none")
    rec = run_config(s, jev, ["quillfield"])
    assert rec.outcome is Outcome.SKIPPED and rec.runs == [] and rec.aggregate is None


def test_mock_matrix_end_to_end(s: Settings) -> None:
    seen: list[str] = []
    res = run_eval(s, progress=seen.append)
    assert [c.name for c in res.configs] == ["mock-rule", "mock-judge"]
    assert len(seen) == 8
    for c in res.configs:
        assert c.outcome is Outcome.OK and c.note is None and len(c.runs) == 4
        assert c.aggregate is not None and c.aggregate.controls == 100
        assert c.aggregate.accuracy == 1.0 and c.aggregate.inherent_tier_correct == 4
        assert all(r.result_hash for r in c.runs)
    only = run_eval(s, ["mock-judge"])
    assert [c.name for c in only.configs] == ["mock-judge"]


def test_failed_run_is_recorded_not_raised(s: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from vendorguard.errors import BudgetExceededError

    def boom(*a: Any, **k: Any) -> Any:
        raise BudgetExceededError("over")

    monkeypatch.setattr(runner, "run_assessment", boom)
    rec = run_config(s, MOCK, ["quillfield"])
    assert rec.outcome is Outcome.FAILED and rec.aggregate is None
    assert rec.runs[0].note == "BudgetExceededError"


def test_aggregate_ignores_failed_runs() -> None:
    assert aggregate([RunRecord(stem="a", outcome=Outcome.FAILED, note="X")]) is None


def test_write_results_is_sorted_and_rounded(s: Settings, tmp_path: Path) -> None:
    res = run_eval(s, ["mock-rule"])
    path = write_results(res, tmp_path / "out" / "results.json", 2)
    text = path.read_text(encoding="utf-8")
    body = json.loads(text)
    assert text.endswith("\n") and body["samples"][0] == "brightdock"
    assert body["configs"][0]["aggregate"]["wall_s"] == round(
        body["configs"][0]["aggregate"]["wall_s"], 2
    )


def test_cli_eval_writes_results_and_rejects_unknown(
    s: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vendorguard.cli.common.load_settings", lambda **_: s)
    r = CliRunner().invoke(app, ["eval", "--configs", "mock-rule"])
    assert r.exit_code == 0, r.output
    assert (s.eval.results_dir / "results.json").is_file()
    bad = CliRunner().invoke(app, ["eval", "--configs", "nope"])
    assert bad.exit_code == 2 and "unknown eval config" in bad.output


def test_cli_determinism_picks_best_config_from_results(
    s: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vendorguard.cli.common.load_settings", lambda **_: s)
    s2 = s.model_copy(update={"eval": s.eval.model_copy(update={"determinism_repeats": 2})})
    monkeypatch.setattr("vendorguard.cli.common.load_settings", lambda **_: s2)
    assert CliRunner().invoke(app, ["eval", "--configs", "mock-judge"]).exit_code == 0
    r = CliRunner().invoke(app, ["determinism"])
    assert r.exit_code == 0, r.output
    assert "mock-judge: 2 repeats" in r.output and "identical result hashes: 100 %" in r.output
    assert (s.eval.results_dir / "determinism.json").is_file()


def test_eval_keeps_configs_that_were_not_rerun(
    s: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vendorguard.cli.common.load_settings", lambda **_: s)
    for name in ("mock-judge", "mock-rule"):  # second run must not drop the first
        assert CliRunner().invoke(app, ["eval", "--configs", name]).exit_code == 0
    body = json.loads((s.eval.results_dir / "results.json").read_text(encoding="utf-8"))
    assert [c["name"] for c in body["configs"]] == ["mock-rule", "mock-judge"]


# ----------------------------------------------------------------------------- review fixes


def _record(name: str, outcome: Outcome, note: str | None = None) -> Any:
    from vendorguard.eval.results import ConfigRecord

    return ConfigRecord(
        name=name,
        llm="mock",
        decider="rule",
        embeddings="none",
        outcome=outcome,
        note=note,
        runs=[],
    )


def test_merge_never_replaces_a_good_result_with_a_skipped_or_failed_one() -> None:
    from vendorguard.eval.results import EvalResults
    from vendorguard.eval.results_io import merge_results

    good = EvalResults(samples=["a"], configs=[_record("jev", Outcome.OK)])
    for bad in (Outcome.SKIPPED, Outcome.FAILED):
        new = EvalResults(samples=["a"], configs=[_record("jev", bad, "no key")])
        merged = merge_results(good, new, ["jev"])
        assert merged.configs[0].outcome is Outcome.OK
    # a good new result does replace; a bad one is kept when there is nothing before
    fresh = EvalResults(samples=["a"], configs=[_record("x", Outcome.SKIPPED, "n")])
    assert merge_results(None, fresh, ["x"]).configs[0].outcome is Outcome.SKIPPED
    bad_then_good = merge_results(
        fresh, EvalResults(samples=["a"], configs=[_record("x", Outcome.OK)]), ["x"]
    )
    assert bad_then_good.configs[0].outcome is Outcome.OK


def test_config_settings_never_uses_the_shared_cache(s: Settings) -> None:
    local = config_settings(s, MOCK)
    assert local.cache.jsonl_dir == s.eval.work_dir / "mock-rule" / "state" / "cache"
    assert local.cache.mode == "read_write"


def test_provenance_names_models_and_prompts_and_marks_the_mock(s: Settings) -> None:
    from vendorguard.eval.runner import provenance

    mock = provenance(s, MOCK)
    assert mock["llm_model"] == "mock" and "embedding_model" not in mock
    assert mock["prompt_mapper"] == s.prompts.mapper
    ollama = EvalConfig(name="o", llm="ollama", decider="jev", embeddings="ollama")
    p = provenance(s, ollama)
    assert p["llm_model"] == s.llm.model and p["jev_model"] == s.decision.jev.model
    assert p["embedding_model"] == s.embeddings.model


def test_stale_configs_flags_changed_or_missing_provenance(s: Settings) -> None:
    from vendorguard.eval.results import EvalResults
    from vendorguard.eval.runner import provenance, stale_configs

    fresh = _record("mock-rule", Outcome.OK).model_copy(update={"provenance": provenance(s, MOCK)})
    old = _record("mock-judge", Outcome.OK)  # recorded before provenance existed
    changed = fresh.model_copy(update={"name": "mock-rule", "provenance": {"llm_model": "other"}})
    assert stale_configs(s, EvalResults(samples=[], configs=[fresh, old])) == ["mock-judge"]
    assert stale_configs(s, EvalResults(samples=[], configs=[changed])) == ["mock-rule"]


def test_a_config_that_lost_runs_or_fell_back_is_not_ok(
    s: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vendorguard.errors import BudgetExceededError

    real = runner.run_assessment
    calls = {"n": 0}

    def sometimes(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise BudgetExceededError("over")
        return real(*a, **k)

    monkeypatch.setattr(runner, "run_assessment", sometimes)
    partial = run_config(s, MOCK, ["quillfield", "brightdock"])
    assert partial.outcome is Outcome.FAILED and "1 of 2 runs failed" in (partial.note or "")
    assert partial.aggregate is not None  # kept for inspection

    monkeypatch.setattr(runner, "run_assessment", real)
    monkeypatch.setattr(runner, "decider_fallbacks", lambda *_: 3)
    fell_back = run_config(s, MOCK, ["quillfield"])
    assert fell_back.outcome is Outcome.FAILED and "fallback decider" in (fell_back.note or "")
    assert fell_back.aggregate is not None and fell_back.aggregate.decider_fallbacks == 3


def test_decider_fallbacks_counts_audit_events(s: Settings) -> None:
    from vendorguard.pipeline.orchestrator import run_assessment

    local = config_settings(s, MOCK)
    result = run_assessment(local, "quillfield", [local.paths.samples_dir / "quillfield.pdf"])
    assert runner.decider_fallbacks(local, result.run_id) == 0


def test_run_eval_reports_each_config_as_it_finishes(s: Settings) -> None:
    seen: list[str] = []
    run_eval(s, on_config=lambda rec: seen.append(rec.name))
    assert seen == ["mock-rule", "mock-judge"]
