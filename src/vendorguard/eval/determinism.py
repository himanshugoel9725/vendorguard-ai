"""Determinism evidence: the same documents assessed several times must give the same result.

``measure`` works on any ready ``Settings`` (cache off for the honest test of a model, a replay
cache for the exactness guarantee); ``run_determinism`` picks a config and forces the cache off.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from vendorguard.config import Settings
from vendorguard.errors import ConfigError
from vendorguard.eval.golden import load_golden
from vendorguard.eval.results import EvalResults, Outcome
from vendorguard.eval.runner import config_settings, sample_stems
from vendorguard.models._base import ContractModel
from vendorguard.models.finding import ControlFinding
from vendorguard.observability.run_manifest import result_hash
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.utils.hashing import hash_obj


class StemDeterminism(ContractModel):
    """Repeated runs of one sample vendor."""

    stem: str
    repeats: int
    result_hashes: list[str]
    hash_identical: bool
    findings: int
    findings_identical: int  # controls whose finding (status, quotes, trace) is equal in every run


class DeterminismReport(ContractModel):
    """Repeated runs of one setup over the samples. ``cache`` says what the runs could reuse."""

    config: str
    cache: str  # "off" or "replay"
    repeats: int
    stems: list[StemDeterminism]
    hash_identical_pct: float
    findings_identical_pct: float


def _finding_hashes(findings: Sequence[ControlFinding]) -> dict[str, str]:
    return {f.control_id: hash_obj(f.model_dump(mode="json")) for f in findings}


def measure_stem(settings: Settings, stem: str, repeats: int) -> StemDeterminism:
    """Assess one sample ``repeats`` times with ``settings`` and compare the runs."""
    golden = load_golden(settings.paths.golden_dir / f"{stem}.json")
    doc = settings.paths.samples_dir / f"{stem}.pdf"
    hashes, per_run = [], []
    for _ in range(repeats):
        result = run_assessment(settings, golden.vendor_id, [doc])
        hashes.append(result_hash(result))
        per_run.append(_finding_hashes(result.findings))
    first = per_run[0]
    same = sum(all(run.get(cid) == h for run in per_run) for cid, h in first.items())
    return StemDeterminism(
        stem=stem,
        repeats=repeats,
        result_hashes=hashes,
        hash_identical=len(set(hashes)) == 1,
        findings=len(first),
        findings_identical=same,
    )


def measure(
    settings: Settings, stems: Sequence[str], repeats: int, *, config: str, cache: str
) -> DeterminismReport:
    """Measure every stem; the percentages pool the vendors."""
    if repeats < 2:
        raise ConfigError("determinism needs at least 2 repeats")
    rows = [measure_stem(settings, stem, repeats) for stem in stems]
    total = sum(r.findings for r in rows)
    return DeterminismReport(
        config=config,
        cache=cache,
        repeats=repeats,
        stems=rows,
        hash_identical_pct=100 * sum(r.hash_identical for r in rows) / len(rows),
        findings_identical_pct=100 * sum(r.findings_identical for r in rows) / total,
    )


def best_config_name(results: EvalResults) -> str | None:
    """The finished config with the best accuracy (ties: macro-F1, then name), or ``None``."""
    ranked = [c for c in results.configs if c.outcome is Outcome.OK and c.aggregate]
    ranked.sort(
        key=lambda c: (
            -(c.aggregate.accuracy if c.aggregate else 0.0),
            -(c.aggregate.macro_f1 if c.aggregate else 0.0),
            c.name,
        )
    )
    return ranked[0].name if ranked else None


def run_determinism(settings: Settings, name: str) -> DeterminismReport:
    """Repeat config ``name`` ``eval.determinism_repeats`` times with the cache OFF."""
    cfg = next((c for c in settings.eval.configs if c.name == name), None)
    if cfg is None:
        raise ConfigError(f"unknown eval config: {name}")
    local = config_settings(settings, cfg)
    local = local.model_copy(update={"cache": local.cache.model_copy(update={"enabled": False})})
    return measure(
        local, sample_stems(local), settings.eval.determinism_repeats, config=name, cache="off"
    )


def write_determinism(report: DeterminismReport, path: Path, digits: int) -> Path:
    """Write the report as sorted JSON; percentages rounded to ``digits``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = report.model_dump(mode="json")
    body["hash_identical_pct"] = round(body["hash_identical_pct"], digits)
    body["findings_identical_pct"] = round(body["findings_identical_pct"], digits)
    path.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "DeterminismReport",
    "StemDeterminism",
    "best_config_name",
    "measure",
    "measure_stem",
    "run_determinism",
    "write_determinism",
]
