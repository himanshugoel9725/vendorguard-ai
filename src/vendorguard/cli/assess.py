"""``vg assess``: run one assessment."""

from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from vendorguard.cli.common import console, guarded, load, open_memory
from vendorguard.errors import ConfigError
from vendorguard.eval.specs import load_spec
from vendorguard.models.run import AssessmentResult
from vendorguard.pipeline.orchestrator import run_assessment


def _overrides(
    llm: str | None,
    decider: str | None,
    embeddings: str | None,
    controls: str | None,
    cache: str | None,
) -> dict[str, object]:
    out: dict[str, dict[str, object]] = {}
    if llm:
        out.setdefault("llm", {})["provider"] = llm
    if decider:
        out.setdefault("decision", {})["provider"] = decider
    if embeddings:
        out.setdefault("embeddings", {})["provider"] = embeddings
    if controls:
        out.setdefault("pipeline", {})["controls_subset"] = [
            c.strip() for c in controls.split(",") if c.strip()
        ]
    if cache == "off":
        out.setdefault("cache", {})["enabled"] = False
    elif cache:
        out.setdefault("cache", {})["mode"] = cache
    return out  # type: ignore[return-value]


def _summary(result: AssessmentResult, run_dir: Path) -> None:
    table = Table(show_header=False, box=None)
    table.add_row("run", result.run_id)
    table.add_row("vendor", escape(f"{result.profile.vendor_name} ({result.vendor_id})"))
    table.add_row("risk score", f"{result.score.overall:g} / 100 ({result.score.band.value})")
    counts: dict[str, int] = {}
    for f in result.findings:
        counts[f.effective_status.value] = counts.get(f.effective_status.value, 0) + 1
    table.add_row("controls", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    table.add_row("cost", f"${result.cost.usd:g}, {result.cost.llm_calls} LLM calls")
    console.print(table)
    console.print(f"reports: {run_dir}", markup=False, soft_wrap=True)


@guarded
def assess(
    vendor: Annotated[str | None, typer.Option(help="Vendor id (required with --docs).")] = None,
    docs: Annotated[
        list[Path] | None, typer.Option(help="Vendor document (repeat for several).")
    ] = None,
    sample: Annotated[str | None, typer.Option(help="A synthetic sample, e.g. quillfield.")] = None,
    llm: Annotated[
        str | None, typer.Option(help="ollama | openai | groq | openai_compat | mock")
    ] = None,
    decider: Annotated[str | None, typer.Option(help="rule | llm_judge | jev | mock")] = None,
    embeddings: Annotated[str | None, typer.Option(help="ollama | none")] = None,
    controls: Annotated[str | None, typer.Option(help="Comma-separated control ids.")] = None,
    cache: Annotated[str | None, typer.Option(help="off | read_write | read_only")] = None,
) -> None:
    """Assess a vendor from its documents and write the reports under the runs folder."""
    settings = load(_overrides(llm, decider, embeddings, controls, cache))
    if sample:
        if vendor or docs:
            raise ConfigError("use either --sample, or --vendor with --docs")
        spec = load_spec(settings.paths.samples_dir / "specs" / f"{sample}.yaml")
        vendor = spec.vendor_id
        docs = [settings.paths.samples_dir / f"{sample}.pdf"]
    if not vendor or not docs:
        raise ConfigError("give --vendor and at least one --docs, or --sample")
    with open_memory(settings) as memory:
        result = run_assessment(settings, vendor, docs, memory=memory)
    _summary(result, settings.paths.runs_dir / result.run_id)


__all__ = ["assess"]
