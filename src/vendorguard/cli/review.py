"""``vg review``: record an analyst override on one control of a finished run."""

from typing import Annotated

import typer

from vendorguard.cli.common import console, guarded, load, open_memory
from vendorguard.controls.loader import load_controls
from vendorguard.models.finding import DraftStatus
from vendorguard.pipeline.override import apply_override
from vendorguard.pipeline.run_index import read_result, run_path


@guarded
def review(
    run_id: str,
    control: Annotated[str, typer.Argument(help="Control id, e.g. IAM-02.")],
    status: Annotated[DraftStatus, typer.Option(help="The analyst's status for the control.")],
    reason: Annotated[str, typer.Option(help="Why the system's status is replaced.")],
    analyst: Annotated[str, typer.Option(help="Who decided.")],
) -> None:
    """Override one control's status; the score and the reports are recomputed."""
    settings = load()
    run_dir = run_path(settings.paths.runs_dir, run_id)
    before = read_result(run_dir)
    controls = load_controls(settings.paths.controls_file)
    with open_memory(settings) as memory:
        after = apply_override(
            settings, controls, run_dir, control, status, reason, analyst, memory=memory
        )
    old, new = before.score, after.score
    console.print(
        f"{control}: now {status.value} (analyst override). "
        f"Score {old.overall:g} ({old.band.value}) -> {new.overall:g} ({new.band.value}).",
        markup=False,
    )


__all__ = ["review"]
