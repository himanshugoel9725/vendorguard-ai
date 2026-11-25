"""Reading side of ``results.json``: merging new configs into it and writing it."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from vendorguard.eval.results import EvalResults, Outcome


def merge_results(
    existing: EvalResults | None, new: EvalResults, order: Sequence[str]
) -> EvalResults:
    """``new`` configs replace same-named ones in ``existing``, except that a skipped or failed
    record never replaces a good one. Configs come out in the order of ``eval.configs`` (names
    no longer configured go last, by name)."""
    by_name = {c.name: c for c in (existing.configs if existing else [])}
    for record in new.configs:
        old = by_name.get(record.name)
        if record.outcome is not Outcome.OK and old is not None and old.outcome is Outcome.OK:
            continue
        by_name[record.name] = record
    rank = {n: i for i, n in enumerate(order)}
    configs = sorted(by_name.values(), key=lambda c: (rank.get(c.name, len(rank)), c.name))
    return EvalResults(samples=new.samples, configs=configs)


def _round(value: Any, digits: int) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {k: _round(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v, digits) for v in value]
    return value


def write_results(results: EvalResults, path: Path, digits: int) -> Path:
    """Write ``results.json`` (sorted keys, floats rounded to ``digits``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _round(results.model_dump(mode="json"), digits)
    path.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = ["merge_results", "write_results"]
