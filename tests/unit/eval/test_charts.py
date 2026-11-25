"""Evaluation charts: files are real PNGs, stable, and leave the mock out of the bars."""

from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.eval.charts import FILES, _model_configs, render_charts
from vendorguard.eval.metrics import GOLD_LABELS, PRED_LABELS, EvalMetrics
from vendorguard.eval.results import (
    Aggregate,
    ConfigRecord,
    EvalResults,
    Outcome,
    RunRecord,
)

PNG = b"\x89PNG\r\n\x1a\n"


def _metrics() -> EvalMetrics:
    confusion = {g: dict.fromkeys(PRED_LABELS, 0) for g in GOLD_LABELS}
    confusion["met"]["met"] = 3
    confusion["met"]["no_evidence"] = 1
    return EvalMetrics(
        controls=4,
        accuracy=0.75,
        macro_f1=0.5,
        per_status={},
        confusion=confusion,
        citation_validity_rate=1.0,
        human_review_rate=0.0,
        triage_skip_rate=0.0,
    )


def _config(name: str, llm: str, accuracy: float, outcome: Outcome = Outcome.OK) -> ConfigRecord:
    agg = Aggregate(
        runs=1,
        controls=4,
        accuracy=accuracy,
        macro_f1=accuracy,
        human_review_rate=0,
        triage_skip_rate=0,
        citation_validity_rate=1.0,
        inherent_tier_correct=1,
        llm_calls=3,
        tokens_in=2000,
        tokens_out=300,
        decider_calls=0,
        usd=0,
        wall_s=1,
    )
    run = RunRecord(stem="a", outcome=Outcome.OK, metrics=_metrics())
    return ConfigRecord(
        name=name,
        llm=llm,
        decider="rule",
        embeddings="none",
        outcome=outcome,
        runs=[run],
        aggregate=agg,
    )


@pytest.fixture
def results() -> EvalResults:
    return EvalResults(
        samples=["a"],
        configs=[
            _config("mock-base", "mock", 1.0),
            _config("m-low", "ollama", 0.3),
            _config("m-high", "ollama", 0.6),
            _config("m-failed", "ollama", 0.9, Outcome.FAILED),
        ],
    )


def test_model_configs_skip_mock_and_failed_and_sort(results: EvalResults) -> None:
    assert [c.name for c in _model_configs(results)] == ["m-high", "m-low"]
    with pytest.raises(ConfigError, match="no finished model config"):
        _model_configs(EvalResults(samples=[], configs=[_config("m", "mock", 1.0)]))


def test_render_charts_writes_three_stable_pngs(
    results: EvalResults, settings_override: Callable[..., Settings], tmp_path: Path
) -> None:
    cs = settings_override().eval.charts
    first = render_charts(results, cs, tmp_path / "a")
    second = render_charts(results, cs, tmp_path / "b")
    assert [p.name for p in first] == list(FILES.values())
    for one, two in zip(first, second, strict=True):
        assert one.read_bytes().startswith(PNG) and one.stat().st_size > 2000
        assert one.read_bytes() == two.read_bytes()  # no timestamps: byte-stable


def test_cli_charts(
    results: EvalResults,
    settings_override: Callable[..., Settings],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from vendorguard.cli.main import app

    s = settings_override(eval={"results_dir": tmp_path / "res"})
    monkeypatch.setattr("vendorguard.cli.common.load_settings", lambda **_: s)
    assert CliRunner().invoke(app, ["charts"]).exit_code == 2  # no results.json yet
    (tmp_path / "res").mkdir()
    (tmp_path / "res" / "results.json").write_text(results.model_dump_json(), encoding="utf-8")
    ok = CliRunner().invoke(app, ["charts"])
    assert ok.exit_code == 0, ok.output
    assert (tmp_path / "res" / "charts" / FILES["accuracy"]).is_file()


def test_vg_starts_without_matplotlib(tmp_path: Path) -> None:
    """`vg` must import in a production install, where matplotlib (a dev dependency) is absent."""
    import subprocess
    import sys

    code = "import sys; sys.modules['matplotlib'] = None; import vendorguard.cli.main; print('ok')"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert out.stdout.strip() == "ok", out.stderr
