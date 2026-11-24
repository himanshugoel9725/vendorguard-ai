"""Render the report files of a finished run folder (used by the pipeline and ``vg report``)."""

from pathlib import Path

from vendorguard.config_models.core import ReportingSettings
from vendorguard.errors import ConfigError
from vendorguard.models.control import ControlSet
from vendorguard.models.run import AssessmentResult
from vendorguard.observability.audit_log import read_audit_log
from vendorguard.observability.run_manifest import read_manifest
from vendorguard.reporting.html import render_html
from vendorguard.reporting.json_export import render_json
from vendorguard.reporting.markdown import render_markdown
from vendorguard.reporting.view import build_view
from vendorguard.utils.jsonio import read_json

FILES = {"json": "report.json", "md": "report.md", "html": "report.html"}


def render_reports(
    run_dir: Path,
    controls: ControlSet,
    settings: ReportingSettings,
    formats: list[str] | None = None,
) -> list[Path]:
    """Write ``report.<ext>`` for each format (default ``reporting.formats``) from the files of
    ``run_dir`` and return the paths. The audit summary appears only if
    ``reporting.include_audit_trail`` is on."""
    result_file = run_dir / "result.json"
    if not result_file.is_file():
        raise ConfigError(f"{run_dir.name} has no result.json (the run did not finish)")
    result = AssessmentResult.model_validate(read_json(result_file))
    manifest_file = run_dir / "manifest.json"
    manifest = read_manifest(manifest_file) if manifest_file.is_file() else None
    events = read_audit_log(run_dir / "audit.jsonl") if settings.include_audit_trail else None
    view = build_view(result, controls, manifest, events)
    texts = {
        "json": lambda: render_json(result, view["manifest"], view["audit"]),
        "md": lambda: render_markdown(view),
        "html": lambda: render_html(view),
    }
    written: list[Path] = []
    for fmt in formats if formats is not None else settings.formats:
        if fmt not in texts:
            raise ConfigError(f"unknown report format '{fmt}'")
        path = run_dir / FILES[fmt]
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(texts[fmt](), encoding="utf-8")
        tmp.replace(path)
        written.append(path)
    return written


__all__ = ["FILES", "render_reports"]
