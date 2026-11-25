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
from vendorguard.eval.runner import (
    config_settings,
    run_config,
    run_eval,
    sample_stems,
    skip_reason,
    write_results,
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
