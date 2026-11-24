"""``vg vendors list|history``: read from the memory store."""

from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from vendorguard.cli.common import console, guarded, load, open_memory

vendors_app = typer.Typer(help="Vendors assessed so far.", no_args_is_help=True)


@vendors_app.command("list")
@guarded
def vendors_list() -> None:
    """List vendors with their number of runs and latest band."""
    table = Table("vendor", "name", "runs", "latest band")
    with open_memory(load()) as memory:
        for v in memory.list_vendors():
            band = v.latest_band.value if v.latest_band else "-"
            table.add_row(escape(v.vendor_id), escape(v.name), str(v.runs), band)
    console.print(table)


@vendors_app.command("history")
@guarded
def vendors_history(vendor_id: Annotated[str, typer.Argument()]) -> None:
    """The runs of one vendor, newest first."""
    table = Table("run", "score", "band", "created")
    with open_memory(load()) as memory:
        for a in memory.list_assessments(vendor_id):
            table.add_row(
                escape(a.run_id),
                f"{a.overall:g}",
                a.band.value,
                a.created_at.isoformat(timespec="seconds"),
            )
    console.print(table)


__all__ = ["vendors_app"]
