"""Evaluation runner: every config of ``eval.configs`` over every sample vendor."""

import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from vendorguard.config import Settings
from vendorguard.config_models.core import EvalConfig
from vendorguard.errors import VendorGuardError
from vendorguard.eval.golden import load_golden
from vendorguard.eval.metrics import evaluate
from vendorguard.eval.results import (
    ConfigRecord,
    EvalResults,
    Outcome,
    RunRecord,
    aggregate,
)
from vendorguard.observability.run_manifest import result_hash
from vendorguard.pipeline.orchestrator import run_assessment
from vendorguard.utils.timeutil import monotonic_s

log = logging.getLogger(__name__)
KEYED_LLMS = ("openai", "groq", "openai_compat")  # hosted profiles that need an API key
Progress = Callable[[str], None]


def sample_stems(settings: Settings) -> list[str]:
    """Stems of the sample vendors (one spec file each), sorted."""
    return sorted(p.stem for p in (settings.paths.samples_dir / "specs").glob("*.yaml"))


def skip_reason(settings: Settings, cfg: EvalConfig) -> str | None:
    """Why ``cfg`` cannot run here (missing API key), or ``None``."""
    if cfg.decider == "jev" and not settings.decision.jev.api_key.get_secret_value():
        return "no Jev API key (VG_DECISION__JEV__API_KEY)"
    if cfg.llm in KEYED_LLMS:
        profile = getattr(settings.llm, cfg.llm)
        if not profile.api_key.get_secret_value():
            return f"no API key for llm.{cfg.llm} (VG_LLM__{cfg.llm.upper()}__API_KEY)"
    return None


def config_settings(settings: Settings, cfg: EvalConfig) -> Settings:
    """``settings`` with the config's providers and isolated paths under ``eval.work_dir``."""
    root = settings.eval.work_dir / cfg.name
    return settings.model_copy(
        update={
            "llm": settings.llm.model_copy(update={"provider": cfg.llm}),
            "decision": settings.decision.model_copy(update={"provider": cfg.decider}),
            "embeddings": settings.embeddings.model_copy(update={"provider": cfg.embeddings}),
            "paths": settings.paths.model_copy(
                update={"runs_dir": root / "runs", "state_dir": root / "state"}
            ),
            "cache": settings.cache.model_copy(
                update={
                    "enabled": settings.eval.cache_enabled,
                    "sqlite_path": root / "state" / "cache.db",
                }
            ),
        }
    )


def _run_one(settings: Settings, stem: str) -> RunRecord:
    golden = load_golden(settings.paths.golden_dir / f"{stem}.json")
    started = monotonic_s()
    try:
        result = run_assessment(
            settings, golden.vendor_id, [settings.paths.samples_dir / f"{stem}.pdf"]
        )
    except VendorGuardError as exc:
        wall = monotonic_s() - started
        return RunRecord(stem=stem, outcome=Outcome.FAILED, note=type(exc).__name__, wall_s=wall)
    wall = monotonic_s() - started
    c = result.cost
    return RunRecord(
        stem=stem,
        outcome=Outcome.OK,
        metrics=evaluate(result.findings, golden.controls),
        inherent_tier_correct=result.inherent_risk.tier is golden.expected_inherent_tier,
        score=result.score.overall,
        llm_calls=c.llm_calls,
        tokens_in=c.tokens_in,
        tokens_out=c.tokens_out,
        decider_calls=c.decider_calls,
        cache_hits=c.cache_hits,
        usd=c.usd,
        wall_s=wall,
        result_hash=result_hash(result),
    )


def run_config(
    settings: Settings, cfg: EvalConfig, stems: Sequence[str], progress: Progress | None = None
) -> ConfigRecord:
    """Run one config over ``stems``; a missing key skips it, a failed run is recorded."""
    head = {"name": cfg.name, "llm": cfg.llm, "decider": cfg.decider, "embeddings": cfg.embeddings}
    reason = skip_reason(settings, cfg)
    if reason:
        return ConfigRecord(**head, outcome=Outcome.SKIPPED, note=reason, runs=[])
    local = config_settings(settings, cfg)
    runs = []
    for stem in stems:
        if progress:
            progress(f"{cfg.name}: {stem}")
        runs.append(_run_one(local, stem))
    failed = [r for r in runs if r.outcome is Outcome.FAILED]
    outcome = Outcome.FAILED if len(failed) == len(runs) else Outcome.OK
    note = f"{len(failed)} of {len(runs)} runs failed" if failed else None
    return ConfigRecord(**head, outcome=outcome, note=note, runs=runs, aggregate=aggregate(runs))


def run_eval(
    settings: Settings, names: Sequence[str] | None = None, progress: Progress | None = None
) -> EvalResults:
    """Run the named configs (default: all of ``eval.configs``) over every sample vendor."""
    configs = [c for c in settings.eval.configs if not names or c.name in names]
    stems = sample_stems(settings)
    return EvalResults(
        samples=stems, configs=[run_config(settings, c, stems, progress) for c in configs]
    )


def merge_results(
    existing: EvalResults | None, new: EvalResults, order: Sequence[str]
) -> EvalResults:
    """``new`` configs replace same-named ones in ``existing``; the others are kept. Configs
    come out in the order of ``eval.configs`` (names no longer configured go last, by name)."""
    by_name = {c.name: c for c in (existing.configs if existing else [])}
    by_name.update({c.name: c for c in new.configs})
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


__all__ = [
    "config_settings",
    "run_config",
    "run_eval",
    "sample_stems",
    "skip_reason",
    "write_results",
]
