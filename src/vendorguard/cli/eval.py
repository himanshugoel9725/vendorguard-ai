"""``vg eval``: run the evaluation matrix and write ``results.json``."""

from typing import Annotated

import typer
from rich.table import Table

from vendorguard.cli.common import console, guarded, load
from vendorguard.errors import ConfigError
from vendorguard.eval.runner import run_eval, write_results

RESULTS_FILE = "results.json"


@guarded
def eval_matrix(
    configs: Annotated[
        str | None, typer.Option(help="Comma-separated config names (default: all).")
    ] = None,
) -> None:
    """Run the configs of ``eval.configs`` over every sample vendor and write results.json."""
    settings = load()
    names = [n.strip() for n in configs.split(",") if n.strip()] if configs else None
    known = {c.name for c in settings.eval.configs}
    unknown = sorted(set(names or []) - known)
    if unknown:
        raise ConfigError(f"unknown eval config(s): {', '.join(unknown)} (known: {sorted(known)})")
    results = run_eval(settings, names, progress=lambda m: console.print(m, markup=False))
    path = write_results(
        results, settings.eval.results_dir / RESULTS_FILE, settings.eval.round_digits
    )
    table = Table(
        "config", "outcome", "accuracy", "macro-F1", "LLM calls", "tokens in/out", "time s"
    )
    for c in results.configs:
        a = c.aggregate
        table.add_row(
            c.name,
            c.outcome.value + (f" ({c.note})" if c.note else ""),
            f"{a.accuracy:.2f}" if a else "-",
            f"{a.macro_f1:.2f}" if a else "-",
            str(a.llm_calls) if a else "-",
            f"{a.tokens_in}/{a.tokens_out}" if a else "-",
            f"{a.wall_s:.0f}" if a else "-",
        )
    console.print(table)
    console.print(f"written: {path}", markup=False, soft_wrap=True)


__all__ = ["eval_matrix"]
