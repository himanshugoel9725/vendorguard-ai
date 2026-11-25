"""The ``vg`` command."""

import typer

from vendorguard.cli.ask import ask
from vendorguard.cli.assess import assess
from vendorguard.cli.doctor import doctor
from vendorguard.cli.eval import eval_matrix
from vendorguard.cli.review import review
from vendorguard.cli.runs import report, runs_app
from vendorguard.cli.samples import samples
from vendorguard.cli.vendors import vendors_app

app = typer.Typer(
    name="vg",
    help="VendorGuard AI: third-party security risk assessment.",
    no_args_is_help=True,
    add_completion=False,
)
app.command()(doctor)
app.command()(samples)
app.command()(assess)
app.command()(report)
app.command()(review)
app.command()(ask)
app.command(name="eval")(eval_matrix)
app.add_typer(runs_app, name="runs")
app.add_typer(vendors_app, name="vendors")

__all__ = ["app"]
