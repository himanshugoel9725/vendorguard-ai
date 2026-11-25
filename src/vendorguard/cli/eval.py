"""``vg eval``: run the evaluation matrix and write ``results.json``."""

from typing import Annotated

import typer
from rich.table import Table

from vendorguard.cli.common import console, guarded, load
from vendorguard.errors import ConfigError
from vendorguard.eval.determinism import best_config_name, run_determinism, write_determinism
from vendorguard.eval.results import EvalResults
from vendorguard.eval.runner import merge_results, run_eval, write_results

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
    target = settings.eval.results_dir / RESULTS_FILE
    before = (
        EvalResults.model_validate_json(target.read_text("utf-8")) if target.is_file() else None
    )
    results = merge_results(before, results, [c.name for c in settings.eval.configs])
    path = write_results(results, target, settings.eval.round_digits)
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


DETERMINISM_FILE = "determinism.json"


@guarded
def determinism(
    config: Annotated[
        str | None, typer.Option(help="Config name (default: best in results.json).")
    ] = None,
) -> None:
    """Repeat one config with the cache off and report how many results are identical."""
    settings = load()
    results_file = settings.eval.results_dir / RESULTS_FILE
    name = config
    if name is None and results_file.is_file():
        name = best_config_name(EvalResults.model_validate_json(results_file.read_text("utf-8")))
    name = name or settings.eval.configs[0].name
    console.print(f"{name}: {settings.eval.determinism_repeats} repeats, cache off", markup=False)
    report = run_determinism(settings, name)
    path = write_determinism(
        report, settings.eval.results_dir / DETERMINISM_FILE, settings.eval.round_digits
    )
    console.print(
        f"identical result hashes: {report.hash_identical_pct:g} %, "
        f"identical findings: {report.findings_identical_pct:g} %",
        markup=False,
    )
    console.print(f"written: {path}", markup=False, soft_wrap=True)


__all__ = ["determinism", "eval_matrix"]
