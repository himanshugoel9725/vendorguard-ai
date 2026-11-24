"""Tests for the ``vg`` command (offline: mock LLM, settings built without .env)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from vendorguard.cli.doctor import secret_status
from vendorguard.cli.main import app
from vendorguard.config import Settings
from vendorguard.models.run import RunStatus
from vendorguard.pipeline.run_index import list_runs, read_result, run_path

runner = CliRunner()


@pytest.fixture
def base(
    settings_override: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """Settings the CLI will see; tests may add sections to this dict before invoking."""
    extra: dict[str, Any] = {}

    def fake_load(
        path: Path | None = None, overrides: dict[str, Any] | None = None, env_file: Any = None
    ) -> Settings:
        merged = {k: dict(v) for k, v in extra.items()}
        for key, value in (overrides or {}).items():
            merged.setdefault(key, {}).update(value)
        return settings_override(**merged)

    monkeypatch.setattr("vendorguard.cli.common.load_settings", fake_load)
    return extra


def _ok(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_help_lists_every_command() -> None:
    out = _ok("--help")
    for name in ("doctor", "samples", "assess", "report", "runs", "vendors"):
        assert name in out


def test_samples_lists_the_four_vendors(base: dict[str, Any]) -> None:
    out = _ok("samples")
    for stem in ("brightdock", "quillfield", "nimbara-hr"):
        assert stem in out


def test_sample_uses_the_spec_vendor_id_so_year_two_is_the_same_vendor(
    base: dict[str, Any],
) -> None:
    _ok("assess", "--sample", "nimbara-hr")
    _ok("assess", "--sample", "nimbara-hr-y2")
    history = _ok("vendors", "history", "nimbara-hr")
    assert history.count("run_") == 2
    assert "nimbara-hr-y2" not in _ok("vendors", "list")


def test_assess_writes_reports_and_prints_a_summary(base: dict[str, Any]) -> None:
    out = _ok("assess", "--sample", "quillfield")
    assert "risk score" in out and "quillfield" in out
    listing = _ok("runs", "list")
    run_id = next(w for w in listing.split() if w.startswith("run_"))
    assert "done" in listing
    shown = _ok("runs", "show", run_id)
    assert "DAT-01" in shown


def test_controls_option_limits_the_assessment(base: dict[str, Any]) -> None:
    _ok("assess", "--sample", "quillfield", "--controls", "IAM-02, DAT-01")
    run_id = next(w for w in _ok("runs", "list").split() if w.startswith("run_"))
    shown = _ok("runs", "show", run_id)
    assert "IAM-02" in shown and "DAT-01" in shown and "GOV-01" not in shown


@pytest.mark.parametrize(
    "args",
    [
        ["assess"],
        ["assess", "--vendor", "x"],
        ["assess", "--docs", "data/samples/quillfield.txt"],
        ["assess", "--sample", "quillfield", "--vendor", "x"],
        ["assess", "--vendor", "x", "--docs", "no-such-file.pdf"],
        ["assess", "--sample", "no-such-sample"],
        ["assess", "--sample", "quillfield", "--llm", "nope"],
        ["assess", "--sample", "quillfield", "--cache", "sometimes"],
        ["report", "../etc"],
        ["report", "run_000000000000"],
        ["runs", "show", "run_000000000000"],
    ],
)
def test_bad_input_is_a_friendly_error_with_exit_code_2(
    base: dict[str, Any], args: list[str]
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "Traceback" not in result.output and (
        "error" in result.output.lower() or "Usage" in result.output
    )


def test_report_rewrites_one_format_and_rejects_unknown(base: dict[str, Any]) -> None:
    _ok("assess", "--sample", "quillfield")
    run_id = next(w for w in _ok("runs", "list").split() if w.startswith("run_"))
    path = Path(_ok("report", run_id, "--format", "md").strip())
    assert path.name == "report.md" and path.is_file()
    assert runner.invoke(app, ["report", run_id, "--format", "pdf"]).exit_code == 2


def test_cache_off_and_decider_options_reach_the_settings(base: dict[str, Any]) -> None:
    _ok(
        "assess",
        "--sample",
        "brightdock",
        "--cache",
        "off",
        "--decider",
        "mock",
        "--embeddings",
        "none",
    )
    assert "done" in _ok("runs", "list", "--vendor", "brightdock")
    assert "done" not in _ok("runs", "list", "--vendor", "someone-else")


def test_doctor_shows_secret_state_never_values(
    base: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-test-do-not-print-1234567890"
    base["llm"] = {"groq": {"api_key": secret}}
    out = _ok("doctor")
    assert secret not in out
    assert "llm.groq.api_key" in out and "set" in out and "unset" in out


@respx.mock
def test_doctor_checks_ollama_only_when_it_is_used(base: dict[str, Any]) -> None:
    base["llm"] = {"provider": "ollama", "base_url": "http://ollama.test"}
    route = respx.get("http://ollama.test/api/tags").mock(return_value=httpx.Response(200, json={}))
    assert "ok" in _ok("doctor") and route.called
    respx.get("http://ollama.test/api/tags").mock(side_effect=httpx.ConnectError("down"))
    assert "not reachable" in _ok("doctor")


def test_doctor_does_not_call_the_network_for_the_mock(base: dict[str, Any]) -> None:
    with respx.mock(assert_all_called=False) as router:
        _ok("doctor")
        assert not router.calls


def test_secret_status_walks_nested_settings(settings_override: Callable[..., Settings]) -> None:
    s = settings_override(llm={"openai": {"api_key": "x"}})
    status = secret_status(s)
    assert status["llm.openai.api_key"] is True and status["llm.groq.api_key"] is False
    assert all(isinstance(v, bool) for v in status.values())


def test_run_index_orders_runs_and_handles_failed_and_foreign_folders(
    base: dict[str, Any], settings_override: Callable[..., Settings], tmp_path: Path
) -> None:
    s = settings_override()
    _ok("assess", "--sample", "quillfield")
    (s.paths.runs_dir / "not-a-run").mkdir()
    (s.paths.runs_dir / "run_failed00000").mkdir()
    ok = list_runs(s.paths.runs_dir)
    assert [r.status for r in ok] == [RunStatus.DONE]
    manifest = json.loads((ok[0].path / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        run_id="run_failed00000",
        status="failed",
        result_hash=None,
        started_at="2099-01-01T00:00:00Z",
    )
    (s.paths.runs_dir / "run_failed00000" / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    runs = list_runs(s.paths.runs_dir)
    assert [r.run_id for r in runs][0] == "run_failed00000" and runs[0].vendor_id is None
    assert list_runs(s.paths.runs_dir, "quillfield") == [
        r for r in runs if r.vendor_id == "quillfield"
    ]
    assert list_runs(tmp_path / "missing") == []
    assert read_result(run_path(s.paths.runs_dir, ok[0].run_id)).vendor_id == "quillfield"


def test_error_text_with_markup_is_printed_literally(base: dict[str, Any]) -> None:
    result = runner.invoke(app, ["assess", "--sample", "[bold]x[/]"])
    assert result.exit_code == 2, result.output
    assert "Traceback" not in result.output and "MarkupError" not in result.output
    assert "[bold]x[/]" in result.output.replace("\n", "")


def test_error_message_markup_from_a_monkeypatched_function(
    base: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from vendorguard.errors import ConfigError

    def boom(*_: Any, **__: Any) -> None:
        raise ConfigError("bad [red]x[/red] and [/]")

    monkeypatch.setattr("vendorguard.cli.assess.run_assessment", boom)
    result = runner.invoke(app, ["assess", "--sample", "quillfield"])
    assert result.exit_code == 2
    assert "[red]x[/red]" in result.output and "[/]" in result.output


def test_runs_list_shows_bracket_ids_literally(
    base: dict[str, Any], settings_override: Callable[..., Settings]
) -> None:
    _ok("assess", "--sample", "quillfield")
    s = settings_override()
    (run_dir,) = [p for p in s.paths.runs_dir.iterdir() if p.is_dir()]
    mpath = run_dir / "manifest.json"
    data = json.loads(mpath.read_text(encoding="utf-8"))
    data["run_id"] = "[red]x[/red]"
    mpath.write_text(json.dumps(data), encoding="utf-8")
    out = _ok("runs", "list")
    assert "[red]x[/red]" in out.replace("\n", "").replace(" ", "")


# --- vg ask ---------------------------------------------------------------------------------------


def test_ask_answers_with_run_and_control_ids(base: dict[str, Any]) -> None:
    _ok("assess", "--sample", "nimbara-hr")
    _ok("assess", "--sample", "nimbara-hr-y2")
    out = _ok("ask", "nimbara-hr", "What changed for nimbara-hr?")
    for cid in ("IAM-04", "PEO-02", "RES-03", "OPS-02"):
        assert cid in out
    assert "cited:" in out and "run_" in out


def test_ask_unknown_vendor(base: dict[str, Any]) -> None:
    out = _ok("ask", "no-such-vendor", "What changed?")
    assert "No assessments are stored for this vendor." in out and "cited:" not in out


def test_ask_empty_question_exits_2(base: dict[str, Any]) -> None:
    result = runner.invoke(app, ["ask", "nimbara-hr", "   "])
    assert result.exit_code == 2


def test_ask_over_long_question_exits_2(
    base: dict[str, Any], settings_override: Callable[..., Settings]
) -> None:
    limit = settings_override().memory.ask_max_question_chars
    result = runner.invoke(app, ["ask", "nimbara-hr", "q" * (limit + 1)])
    assert result.exit_code == 2


def test_ask_is_listed_in_help() -> None:
    assert "ask" in _ok("--help")
