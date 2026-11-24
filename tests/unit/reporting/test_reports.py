"""Tests for the JSON, Markdown and HTML reports (offline, no model)."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError
from vendorguard.models.finding import Override
from vendorguard.models.run import AssessmentResult, ReassessmentDiff, StatusChange
from vendorguard.observability.audit_log import read_audit_log
from vendorguard.observability.run_manifest import read_manifest
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.reporting.html import render_html
from vendorguard.reporting.json_export import render_json
from vendorguard.reporting.markdown import md, render_markdown
from vendorguard.reporting.render import render_reports
from vendorguard.reporting.view import build_view
from vendorguard.utils.jsonio import read_json

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "data" / "samples" / "quillfield.txt"
Make = Callable[..., Settings]
EVIL = '<script>alert(1)</script> [x](javascript:alert(1)) | **bold** & "q"'


@pytest.fixture
def run(settings_override: Make) -> tuple[Settings, AssessmentResult, Path]:
    s = settings_override()
    result = run_assessment(s, "quillfield", [SAMPLE])
    return s, result, s.paths.runs_dir / result.run_id


def _view(settings: Settings, result: AssessmentResult, run_dir: Path):  # type: ignore[no-untyped-def]
    controls = load_controls(settings.paths.controls_file)
    return build_view(
        result,
        controls,
        read_manifest(run_dir / "manifest.json"),
        read_audit_log(run_dir / "audit.jsonl"),
    )


def test_pipeline_writes_every_configured_format(run) -> None:  # type: ignore[no-untyped-def]
    _, _, run_dir = run
    names = {p.name for p in run_dir.iterdir()}
    assert {"report.json", "report.md", "report.html", "result.json"} <= names
    assert not [n for n in names if n.endswith(".tmp")]


def test_html_is_self_contained_and_offline(run) -> None:  # type: ignore[no-untyped-def]
    _, _, run_dir = run
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    assert "<style>" in html and "<script" not in html.lower()
    assert not re.search(r'(src|href)="https?://', html) and "@import" not in html
    for section in ("Domain risk scores", "Findings", "Audit summary", "Run manifest"):
        assert f"<h2>{section}</h2>" in html
    assert html.count('class="finding"') == 25


def test_reports_are_deterministic_for_the_same_input(run) -> None:  # type: ignore[no-untyped-def]
    s, result, run_dir = run
    view = _view(s, result, run_dir)
    assert render_markdown(view) == render_markdown(view)
    assert render_html(view) == render_html(view)
    assert render_json(result, view["manifest"], view["audit"]) == render_json(
        result, view["manifest"], view["audit"]
    )


def test_json_report_holds_result_manifest_and_audit_summary(run) -> None:  # type: ignore[no-untyped-def]
    _, result, run_dir = run
    body = read_json(run_dir / "report.json")
    assert body["result"]["run_id"] == result.run_id
    assert body["manifest"]["status"] == "done"
    assert body["audit_summary"]["stages"]["cascade.finding"] == 25
    assert set(body["audit_summary"]) == {
        "cached", "events", "fallbacks", "stages", "tokens_in", "tokens_out", "usd",
    }  # fmt: skip


def test_untrusted_text_cannot_inject_html_or_markdown(run) -> None:  # type: ignore[no-untyped-def]
    s, result, run_dir = run
    bad_profile = result.profile.model_copy(update={"vendor_name": EVIL})
    bad_findings = [
        f.model_copy(
            update={
                "rationale": EVIL,
                "citations": [c.model_copy(update={"quote": EVIL}) for c in f.citations],
            }
        )
        for f in result.findings
    ]
    bad = result.model_copy(
        update={"profile": bad_profile, "findings": bad_findings, "summary": EVIL}
    )
    view = _view(s, bad, run_dir)
    html = render_html(view)
    assert "<script>alert" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    text = render_markdown(view)
    assert "<script>" not in text and "[x](" not in text and "\\<script\\>" in text
    assert "\n" not in md("a\nb\r\n# c") and md("# c").startswith("\\#")


def test_override_and_diff_are_shown(run) -> None:  # type: ignore[no-untyped-def]
    s, result, run_dir = run
    first = result.findings[0]
    override = Override(
        analyst="Dana",
        new_status="not_met",
        reason="Seen in audit",
        at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    change = StatusChange(control_id="IAM-02", from_status="met", to_status="not_met")
    diff = ReassessmentDiff(
        previous_run_id="run_old",
        new_gaps=["IAM-02"],
        resolved_gaps=["DAT-01"],
        changed=[change],
        score_delta=-5.0,
    )
    changed = result.model_copy(
        update={
            "findings": [first.model_copy(update={"override": override}), *result.findings[1:]],
            "diff": diff,
        }
    )
    view = _view(s, changed, run_dir)
    for text, previous in ((render_markdown(view), "run\\_old"), (render_html(view), "run_old")):
        assert "Dana" in text and "Seen in audit" in text and previous in text
        assert "-5" in text and "IAM-02" in text
    assert (
        view["findings"][0]["status"] == "not_met"
        and view["findings"][0]["system_status"] != "not_met"
    )
    assert len(view["overrides"]) == 1


def test_audit_trail_can_be_switched_off(settings_override: Make) -> None:
    s = settings_override(reporting={"include_audit_trail": False})
    result = run_assessment(s, "quillfield", [SAMPLE])
    run_dir = s.paths.runs_dir / result.run_id
    assert "Audit summary" not in (run_dir / "report.md").read_text(encoding="utf-8")
    assert read_json(run_dir / "report.json")["audit_summary"] is None


def test_render_reports_errors_and_format_selection(run, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    s, _, run_dir = run
    controls = load_controls(s.paths.controls_file)
    only = render_reports(run_dir, controls, s.reporting, formats=["md"])
    assert [p.name for p in only] == ["report.md"]
    with pytest.raises(ConfigError, match="unknown report format"):
        render_reports(run_dir, controls, s.reporting, formats=["pdf"])
    with pytest.raises(ConfigError, match="no result.json"):
        render_reports(tmp_path, controls, s.reporting)


def test_citations_show_the_document_name_and_page(run) -> None:  # type: ignore[no-untyped-def]
    s, result, run_dir = run
    view = _view(s, result, run_dir)
    cited = [c for f in view["findings"] for c in f["citations"]]
    assert cited and all(c["document"] == "quillfield.txt" for c in cited)
    assert "quillfield.txt" in (run_dir / "report.md").read_text(encoding="utf-8")
