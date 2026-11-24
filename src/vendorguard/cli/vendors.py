"""``vg vendors list|history`` (from the run folders; the memory store takes over in Phase 7)."""

from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from vendorguard.cli.common import console, guarded, load
from vendorguard.pipeline.run_index import list_runs

vendors_app = typer.Typer(help="Vendors assessed so far.", no_args_is_help=True)


@vendors_app.command("list")
@guarded
def vendors_list() -> None:
    """List vendors with their number of runs and latest band."""
    runs = [r for r in list_runs(load().paths.runs_dir) if r.vendor_id]
    table = Table("vendor", "runs", "latest band")
    for vendor in sorted({r.vendor_id for r in runs if r.vendor_id}):
        mine = [r for r in runs if r.vendor_id == vendor]
        table.add_row(escape(vendor), str(len(mine)), mine[0].band or "-")
    console.print(table)


@vendors_app.command("history")
@guarded
def vendors_history(vendor_id: Annotated[str, typer.Argument()]) -> None:
    """The runs of one vendor, newest first."""
    table = Table("run", "status", "score", "band", "started")
    for r in list_runs(load().paths.runs_dir, vendor_id):
        score = "-" if r.overall is None else f"{r.overall:g}"
        table.add_row(
            r.run_id,
            r.status.value,
            score,
            r.band or "-",
            r.started_at.isoformat(timespec="seconds"),
        )
    console.print(table)


__all__ = ["vendors_app"]
