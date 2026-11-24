"""``vg runs list|show`` and ``vg report``."""

import webbrowser
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from vendorguard.cli.common import console, guarded, load
from vendorguard.controls.loader import load_controls
from vendorguard.errors import ConfigError
from vendorguard.pipeline.run_index import list_runs, read_result, run_path
from vendorguard.reporting.render import FILES, render_reports

runs_app = typer.Typer(help="Browse finished runs.", no_args_is_help=True)


@runs_app.command("list")
@guarded
def runs_list(
    vendor: Annotated[str | None, typer.Option(help="Only this vendor id.")] = None,
) -> None:
    """List runs, newest first."""
    settings = load()
    table = Table("run", "vendor", "status", "score", "band", "started")
    for r in list_runs(settings.paths.runs_dir, vendor):
        score = "-" if r.overall is None else f"{r.overall:g}"
        table.add_row(
            escape(r.run_id),
            escape(r.vendor_id or "-"),
            r.status.value,
            score,
            r.band or "-",
            r.started_at.isoformat(timespec="seconds"),
        )
    console.print(table)


@runs_app.command("show")
@guarded
def runs_show(run_id: str) -> None:
    """Show the findings of one run."""
    settings = load()
    result = read_result(run_path(settings.paths.runs_dir, run_id))
    name, score = result.profile.vendor_name, result.score
    console.print(f"{name}: {score.overall:g} ({score.band.value})", markup=False)
    table = Table("control", "status", "rounds")
    for f in result.findings:
        table.add_row(f.control_id, f.effective_status.value, str(f.review_rounds))
    console.print(table)
    console.print(result.summary, markup=False)


@guarded
def report(
    run_id: str,
    format: Annotated[
        str | None, typer.Option(help="json | md | html (default: all configured)")
    ] = None,
    open_: Annotated[
        bool, typer.Option("--open", help="Open the HTML report in a browser.")
    ] = False,
) -> None:
    """(Re)write the reports of a finished run."""
    settings = load()
    if format is not None and format not in FILES:
        raise ConfigError(f"unknown report format '{format}' (use json, md or html)")
    run_dir = run_path(settings.paths.runs_dir, run_id)
    controls = load_controls(settings.paths.controls_file)
    paths = render_reports(run_dir, controls, settings.reporting, [format] if format else None)
    for p in paths:
        console.print(str(p), markup=False, soft_wrap=True)
    html = run_dir / FILES["html"]
    if open_ and html.is_file():
        webbrowser.open(html.as_uri())


__all__ = ["report", "runs_app"]
