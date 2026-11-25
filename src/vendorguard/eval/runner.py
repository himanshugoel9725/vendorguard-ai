"""Evaluation runner: every config of ``eval.configs`` over every sample vendor."""

import logging
from collections.abc import Callable, Sequence

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
from vendorguard.observability.audit_log import read_audit_log
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
                update={  # never touch the shared cache or the committed cassettes
                    "enabled": settings.eval.cache_enabled,
                    "mode": "read_write",
                    "sqlite_path": root / "state" / "cache.db",
                    "jsonl_dir": root / "state" / "cache",
                }
            ),
        }
    )


def decider_fallbacks(settings: Settings, run_id: str) -> int:
    """How many gate decisions of a finished run were made by the fallback decider."""
    events = read_audit_log(settings.paths.runs_dir / run_id / "audit.jsonl")
    return sum(e.stage == "decider_fallback" for e in events)


def provenance(settings: Settings, cfg: EvalConfig) -> dict[str, str]:
    """The models and prompt versions a config's results depend on (no secrets)."""
    profile = getattr(settings.llm, cfg.llm, None)
    model = "mock" if cfg.llm == "mock" else str(getattr(profile, "model", settings.llm.model))
    out = {"llm_model": model}
    if cfg.embeddings != "none":
        out["embedding_model"] = settings.embeddings.model
    if cfg.decider == "jev":
        out["jev_model"] = settings.decision.jev.model
    out.update({f"prompt_{k}": v for k, v in sorted(settings.prompts.model_dump().items())})
    return out


def stale_configs(settings: Settings, results: EvalResults) -> list[str]:
    """Configs in ``results`` whose recorded models/prompts differ from the current settings
    (or were recorded without them)."""
    wanted = {c.name: provenance(settings, c) for c in settings.eval.configs}
    return [c.name for c in results.configs if c.name in wanted and c.provenance != wanted[c.name]]


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
        decider_fallbacks=decider_fallbacks(settings, result.run_id),
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
    prov = provenance(settings, cfg)
    reason = skip_reason(settings, cfg)
    if reason:
        return ConfigRecord(**head, outcome=Outcome.SKIPPED, note=reason, provenance=prov, runs=[])
    local = config_settings(settings, cfg)
    runs = []
    for stem in stems:
        if progress:
            progress(f"{cfg.name}: {stem}")
        runs.append(_run_one(local, stem))
    failed = [r for r in runs if r.outcome is Outcome.FAILED]
    fallbacks = sum(r.decider_fallbacks for r in runs)
    notes = []
    if failed:
        notes.append(f"{len(failed)} of {len(runs)} runs failed")
    if fallbacks:
        notes.append(f"{fallbacks} gate decisions came from the fallback decider")
    # a config that lost runs or fell back is not comparable with the others: not OK
    outcome = Outcome.FAILED if notes else Outcome.OK
    return ConfigRecord(
        **head,
        outcome=outcome,
        note="; ".join(notes) or None,
        provenance=prov,
        runs=runs,
        aggregate=aggregate(runs),
    )


def run_eval(
    settings: Settings,
    names: Sequence[str] | None = None,
    progress: Progress | None = None,
    on_config: Callable[[ConfigRecord], None] | None = None,
) -> EvalResults:
    """Run the named configs (default: all of ``eval.configs``) over every sample vendor.
    ``on_config`` is called after each finished config, so a crash keeps the earlier ones."""
    configs = [c for c in settings.eval.configs if not names or c.name in names]
    stems = sample_stems(settings)
    records = []
    for cfg in configs:
        record = run_config(settings, cfg, stems, progress)
        records.append(record)
        if on_config:
            on_config(record)
    return EvalResults(samples=stems, configs=records)


__all__ = [
    "config_settings",
    "decider_fallbacks",
    "provenance",
    "run_config",
    "run_eval",
    "sample_stems",
    "skip_reason",
    "stale_configs",
]
