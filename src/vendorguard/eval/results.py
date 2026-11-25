"""Result records of an evaluation run (what ``results.json`` contains) and their aggregation."""

from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field

from vendorguard.eval.metrics import (
    GOLD_LABELS,
    PRED_LABELS,
    EvalMetrics,
    macro_f1,
)
from vendorguard.models._base import ContractModel


class Outcome(StrEnum):
    """How a run or a config ended."""

    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"


class RunRecord(ContractModel):
    """One sample vendor assessed with one config."""

    stem: str
    outcome: Outcome
    note: str | None = None  # error class for a failed run
    metrics: EvalMetrics | None = None
    inherent_tier_correct: bool | None = None
    score: float | None = None
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    decider_calls: int = 0
    cache_hits: int = 0
    decider_fallbacks: int = (
        0  # gate decisions made by the fallback decider, not the configured one
    )
    usd: float = 0.0
    wall_s: float = 0.0
    result_hash: str | None = None


class Aggregate(ContractModel):
    """Successful runs of a config pooled: controls are pooled; citation validity is the mean of the
    per-vendor rates."""

    runs: int
    controls: int
    accuracy: float
    macro_f1: float
    human_review_rate: float
    triage_skip_rate: float
    citation_validity_rate: float | None
    inherent_tier_correct: int
    llm_calls: int
    tokens_in: int
    tokens_out: int
    decider_calls: int
    decider_fallbacks: int = 0
    usd: float
    wall_s: float


class ConfigRecord(ContractModel):
    """One row of the evaluation matrix with its runs."""

    name: str
    llm: str
    decider: str
    embeddings: str
    outcome: Outcome
    note: str | None = None
    provenance: dict[str, str] = Field(default_factory=dict)  # models and prompt versions used
    runs: list[RunRecord]
    aggregate: Aggregate | None = None


class EvalResults(ContractModel):
    """The whole ``results.json``."""

    samples: list[str]
    configs: list[ConfigRecord]


def aggregate(runs: Sequence[RunRecord]) -> Aggregate | None:
    """Pool the successful runs; ``None`` if there is none."""
    ok = [r for r in runs if r.outcome is Outcome.OK and r.metrics is not None]
    metrics = [r.metrics for r in ok if r.metrics is not None]
    if not metrics:
        return None
    matrix = {g: dict.fromkeys(PRED_LABELS, 0) for g in GOLD_LABELS}
    total = 0
    for m in metrics:
        total += m.controls
        for g, row in m.confusion.items():
            for p, n in row.items():
                matrix[g][p] += n
    correct = sum(matrix[g][g] for g in GOLD_LABELS)
    cites = [m.citation_validity_rate for m in metrics if m.citation_validity_rate is not None]
    reviews = sum(round(m.human_review_rate * m.controls) for m in metrics)  # exact: k / n * n
    skips = sum(round(m.triage_skip_rate * m.controls) for m in metrics)
    return Aggregate(
        runs=len(ok),
        controls=total,
        accuracy=correct / total,
        macro_f1=macro_f1(matrix),
        human_review_rate=reviews / total,
        triage_skip_rate=skips / total,
        citation_validity_rate=sum(cites) / len(cites) if cites else None,
        inherent_tier_correct=sum(bool(r.inherent_tier_correct) for r in ok),
        llm_calls=sum(r.llm_calls for r in ok),
        tokens_in=sum(r.tokens_in for r in ok),
        tokens_out=sum(r.tokens_out for r in ok),
        decider_calls=sum(r.decider_calls for r in ok),
        decider_fallbacks=sum(r.decider_fallbacks for r in ok),
        usd=sum(r.usd for r in ok),
        wall_s=sum(r.wall_s for r in ok),
    )


__all__ = [
    "Aggregate",
    "ConfigRecord",
    "EvalResults",
    "Outcome",
    "RunRecord",
    "aggregate",
]
