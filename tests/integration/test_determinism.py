"""Determinism evidence: mock with the cache off, and the committed cassettes in replay."""

from collections.abc import Callable
from pathlib import Path

import pytest
import respx

from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.eval.determinism import (
    best_config_name,
    measure,
    measure_stem,
    run_determinism,
    write_determinism,
)
from vendorguard.eval.results import ConfigRecord, EvalResults, Outcome
from vendorguard.models.finding import ControlStatus

ROOT = Path(__file__).resolve().parents[2]
STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]
Make = Callable[..., Settings]


def test_mock_with_cache_off_is_fully_deterministic(
    settings_override: Make, tmp_path: Path
) -> None:
    s = settings_override(
        eval={"work_dir": tmp_path / "eval", "determinism_repeats": 3},
    )
    report = run_determinism(s, "keyword-baseline")
    assert report.cache == "off" and report.repeats == 3
    assert report.hash_identical_pct == 100.0 and report.findings_identical_pct == 100.0
    assert all(len(set(r.result_hashes)) == 1 and len(r.result_hashes) == 3 for r in report.stems)
    out = write_determinism(report, tmp_path / "d" / "determinism.json", 2)
    assert '"hash_identical_pct": 100.0' in out.read_text(encoding="utf-8")


def test_replay_is_100_percent_identical(settings_override: Make) -> None:
    s = settings_override(
        llm={"provider": "ollama"},
        embeddings={"provider": "none"},
        cache={
            "enabled": True,
            "backend": "jsonl",
            "mode": "read_only",
            "jsonl_dir": ROOT / "tests" / "cassettes",
        },
    )
    with respx.mock(assert_all_called=False) as network:
        report = measure(s, STEMS, 2, config="replay", cache="replay")
        assert not network.calls
    assert report.hash_identical_pct == 100.0 and report.findings_identical_pct == 100.0


def test_a_run_that_changes_between_repeats_is_detected(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vendorguard.eval import determinism as mod

    real = mod.run_assessment
    calls = {"n": 0}

    def flaky(*a: object, **k: object) -> object:
        calls["n"] += 1
        result = real(*a, **k)  # type: ignore[arg-type]
        if calls["n"] == 2:
            first = result.findings[0]  # type: ignore[attr-defined]
            flipped = (
                ControlStatus.MET
                if first.status is not ControlStatus.MET
                else ControlStatus.NOT_MET
            )
            result.findings[0] = first.model_copy(update={"status": flipped})  # type: ignore[attr-defined]
        return result

    monkeypatch.setattr(mod, "run_assessment", flaky)
    row = measure_stem(settings_override(), "quillfield", 2)
    assert not row.hash_identical and row.findings_identical == row.findings - 1


def test_guards(settings_override: Make) -> None:
    s = settings_override()
    with pytest.raises(ConfigError, match="2 repeats"):
        measure(s, ["quillfield"], 1, config="x", cache="off")
    with pytest.raises(ConfigError, match="unknown eval config"):
        run_determinism(s, "nope")


def test_best_config_prefers_accuracy_then_name() -> None:
    def rec(name: str, acc: float, outcome: Outcome = Outcome.OK) -> ConfigRecord:
        from vendorguard.eval.results import Aggregate

        agg = Aggregate(
            runs=1,
            controls=1,
            accuracy=acc,
            macro_f1=acc,
            human_review_rate=0,
            triage_skip_rate=0,
            citation_validity_rate=None,
            inherent_tier_correct=1,
            llm_calls=0,
            tokens_in=0,
            tokens_out=0,
            decider_calls=0,
            usd=0,
            wall_s=0,
        )
        return ConfigRecord(
            name=name,
            llm="mock",
            decider="rule",
            embeddings="none",
            outcome=outcome,
            runs=[],
            aggregate=agg,
        )

    res = EvalResults(
        samples=[], configs=[rec("b", 0.8), rec("a", 0.8), rec("c", 0.9, Outcome.FAILED)]
    )
    assert best_config_name(res) == "a"
    assert best_config_name(EvalResults(samples=[], configs=[])) is None
