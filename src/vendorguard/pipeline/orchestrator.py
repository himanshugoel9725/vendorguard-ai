"""The assessment pipeline: documents in, scored and audited ``AssessmentResult`` out.

The one big module. Stages: validate -> ingest -> chunk -> retrieve -> intake -> inherent risk ->
controls (thread pool) -> score -> diff -> summary -> persist -> manifest. LLMs extract and draft;
Python decides the flow and computes the scores.
"""

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vendorguard.agents.intake import IntakeAgent
from vendorguard.agents.mapper import MapperAgent
from vendorguard.agents.reporter import ReporterAgent
from vendorguard.agents.reviewer import ReviewerAgent
from vendorguard.config import Settings
from vendorguard.controls.loader import load_controls
from vendorguard.diff.reassessment import compute_diff, find_previous
from vendorguard.errors import ConfigError
from vendorguard.factory import DeciderDeps, Providers, build_decider, build_providers
from vendorguard.ingest.chunker import chunk_document
from vendorguard.ingest.loader import load_document
from vendorguard.ingest.text_cleaner import clean_document
from vendorguard.interfaces.decider import Decider
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.models.control import ControlSet
from vendorguard.models.document import Document
from vendorguard.models.evidence import Chunk
from vendorguard.models.finding import ControlFinding
from vendorguard.models.run import (
    AssessmentResult,
    ManifestInput,
    ReassessmentDiff,
    RunManifest,
    RunStatus,
)
from vendorguard.models.score import RiskScore
from vendorguard.observability.audit_log import AuditLog
from vendorguard.observability.metrics import Metrics
from vendorguard.observability.run_manifest import (
    current_git_sha,
    finish_manifest,
    result_hash,
    start_manifest,
    write_manifest,
)
from vendorguard.pipeline.context import RunContext
from vendorguard.pipeline.control_cascade import run_cascade
from vendorguard.pipeline.retrieval_plan import ControlEvidence, plan_evidence
from vendorguard.pipeline.run_folder import (
    AUDIT_FILE,
    MANIFEST_FILE,
    persist_result,
    prepare_run_dir,
)
from vendorguard.pipeline.run_index import RUN_ID_PATTERN, VENDOR_ID_PATTERN
from vendorguard.reporting.facts import build_facts
from vendorguard.reporting.render import render_reports
from vendorguard.scoring.inherent_risk import inherent_risk
from vendorguard.scoring.rules_engine import score_findings
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.ids import make_run_id
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow
from vendorguard.verification.citation_check import CitationChecker

log = logging.getLogger(__name__)

# Hooks: ``render`` replaces the default report writer, ``differ`` the default ``compute_diff``.
Differ = Callable[[list[ControlFinding], RiskScore, AssessmentResult], ReassessmentDiff]
Renderer = Callable[[AssessmentResult, Path], None]
PROMPT_AGENTS = ("intake", "mapper", "reviewer", "reporter")


def _load_documents(paths: Sequence[Path], settings: Settings) -> list[Document]:
    """Load and clean every file; identical files count once; sorted by content hash."""
    docs = {
        d.sha256: d
        for d in (clean_document(load_document(p, settings.ingest), settings.ingest) for p in paths)
    }
    return [docs[k] for k in sorted(docs)]


def _select_controls(settings: Settings, controls: ControlSet | None) -> ControlSet:
    """The controls to assess: all, or ``pipeline.controls_subset`` (empty list = all)."""
    everything = controls or load_controls(settings.paths.controls_file)
    subset = settings.pipeline.controls_subset
    chosen = everything.subset(subset) if subset else everything
    if not chosen.controls:
        raise ConfigError("no controls to assess")
    return chosen


def _providers_label(settings: Settings, llm_model: str) -> dict[str, str]:
    cache = settings.cache
    return {
        "llm": f"{settings.llm.provider}/{llm_model}",
        "embeddings": f"{settings.embeddings.provider}/{settings.embeddings.model}",
        "decider": settings.decision.provider,
        "cache": f"{cache.backend}:{cache.mode}" if cache.enabled else "off",
    }


def _llm_model(settings: Settings) -> str:
    """The model name of the active LLM profile (hosted profiles carry their own)."""
    profile = getattr(settings.llm, settings.llm.provider, None)
    return str(getattr(profile, "model", settings.llm.model))


def _assess_controls(
    ctx: RunContext, controls: ControlSet, evidence: dict[str, ControlEvidence]
) -> list[ControlFinding]:
    """Run the cascade of every control on a thread pool; the result is sorted by control ID.

    The first failure (by control ID, so it is deterministic) stops the other workers and is
    re-raised. Only model or schema failures are absorbed, per control, inside the cascade.
    """

    def work(control_id: str) -> ControlFinding | None:
        if ctx.abort.is_set():
            return None
        try:
            control = next(c for c in controls.controls if c.id == control_id)
            return run_cascade(ctx, control, evidence[control_id])
        except BaseException:
            ctx.abort.set()
            raise

    ids = sorted(c.id for c in controls.controls)
    with ThreadPoolExecutor(max_workers=ctx.settings.pipeline.max_concurrency) as pool:
        futures = [pool.submit(work, cid) for cid in ids]
    findings: list[ControlFinding] = []
    for future in futures:
        finding = future.result()
        if finding is not None:
            findings.append(finding)
    return sorted(findings, key=lambda f: f.control_id)


def _execute(
    ctx: RunContext,
    vendor_id: str,
    chunks: list[Chunk],
    controls: ControlSet,
    memory: MemoryStore | None,
    differ: Differ | None,
) -> AssessmentResult:
    s = ctx.settings
    evidence = plan_evidence(chunks, controls, ctx.embedder, s, ctx.audit)
    profile = ctx.intake.extract(chunks)
    inherent = inherent_risk(profile, s.scoring.inherent_risk)
    findings = _assess_controls(ctx, controls, evidence)
    score = score_findings(findings, controls, inherent.tier, s.scoring)
    previous = find_previous(memory, vendor_id, ctx.run_id) if memory else None
    diff = (differ or compute_diff)(findings, score, previous) if previous else None
    facts = build_facts(profile.vendor_name, inherent, score, findings, diff)
    result = AssessmentResult(
        run_id=ctx.run_id,
        vendor_id=vendor_id,
        created_at=utcnow(),
        profile=profile,
        inherent_risk=inherent,
        findings=findings,
        score=score,
        diff=diff,
        summary=ctx.reporter.summarize(facts),
        cost=ctx.cost.summary(),
        manifest_path=ctx.run_dir / MANIFEST_FILE,
    )
    persist_result(ctx.run_dir, result)
    return result


def _record_failure(audit: AuditLog, stage: str, run_id: str, exc: BaseException) -> None:
    """One audit event with the error class only. Never raises (it must not mask the error)."""
    try:
        audit.record(
            stage=stage,
            actor="python",
            input_hash=hash_obj(run_id),
            output_hash=hash_obj(type(exc).__name__),
            tokens_in=0,
            tokens_out=0,
            usd=0.0,
            latency_ms=0.0,
            cached=False,
        )
    except Exception:
        log.warning("could not write the %s audit event", stage)


def _fail(ctx_audit: AuditLog, manifest: RunManifest, run_dir: Path, exc: BaseException) -> None:
    """Record the failure (error class only) and write the manifest with status ``failed``."""
    _record_failure(ctx_audit, "run.failed", manifest.run_id, exc)
    try:
        write_manifest(run_dir / MANIFEST_FILE, finish_manifest(manifest, RunStatus.FAILED))
    except Exception:
        log.warning("could not write the failed manifest of run %s", manifest.run_id)


def run_assessment(
    settings: Settings,
    vendor_id: str,
    doc_paths: Sequence[Path],
    *,
    controls: ControlSet | None = None,
    providers: Providers | None = None,
    memory: MemoryStore | None = None,
    differ: Differ | None = None,
    render: Renderer | None = None,
    metrics: Metrics | None = None,
    run_id: str | None = None,
) -> AssessmentResult:
    """Assess one vendor from its documents and persist the run under ``paths.runs_dir``.

    Providers given by the caller are NOT closed; ones built here are. Errors before the run
    folder exists (bad input, unreadable file) raise without leaving a run behind; later errors
    also write a manifest with ``status: failed`` and an audit event, then re-raise.
    """
    if not VENDOR_ID_PATTERN.match(vendor_id):
        raise ConfigError(
            "vendor_id: 1-64 letters, digits, '.', '_' or '-', starting with a letter or digit"
        )
    if run_id is not None and not RUN_ID_PATTERN.match(run_id):
        raise ConfigError(f"'{run_id}' is not a valid run id")
    if not doc_paths:
        raise ConfigError("at least one document is required")
    chosen = _select_controls(settings, controls)
    docs = _load_documents(doc_paths, settings)
    chunks = sorted(
        (c for d in docs for c in chunk_document(d, settings.chunking)), key=lambda c: c.chunk_id
    )
    if not chunks:
        raise ConfigError("the documents contain no text")
    prompts = PromptLoader(settings.paths.prompts_dir, settings.prompts)
    names = (*PROMPT_AGENTS, "judge") if "llm_judge" in _decider_names(settings) else PROMPT_AGENTS
    rid = run_id or make_run_id(
        vendor_id,
        [d.sha256 for d in docs],
        settings.fingerprint(),
        deterministic=settings.pipeline.deterministic_run_ids,
    )
    manifest = start_manifest(
        rid,
        settings,
        controls_version=chosen.version,
        prompt_hashes={n: prompts.load(n).prompt_hash for n in names},
        providers=_providers_label(settings, _llm_model(settings)),
        inputs=[
            ManifestInput(filename=d.filename, sha256=d.sha256, pages=len(d.pages)) for d in docs
        ],
        git_sha=current_git_sha(Path.cwd(), settings.observability.git_timeout_s),
    )
    run_dir = prepare_run_dir(settings.paths.runs_dir, rid)
    write_manifest(run_dir / MANIFEST_FILE, manifest)
    audit = AuditLog(run_dir / AUDIT_FILE, rid, on_event=metrics.observe_event if metrics else None)
    built = providers is None
    prov: Providers | None = providers
    decider: Decider | None = None
    try:
        try:
            prov = prov or build_providers(settings)
            decider = build_decider(settings, DeciderDeps(prov.llm, prompts, audit, prov.tracker))
            ctx = _context(settings, rid, run_dir, audit, prov, prompts, decider)
            result = _execute(ctx, vendor_id, chunks, chosen, memory, differ)
            done = finish_manifest(manifest, RunStatus.DONE, result_hash(result))
            write_manifest(run_dir / MANIFEST_FILE, done)
        except BaseException as exc:  # includes KeyboardInterrupt: never leave 'running' behind
            log.error("run %s failed: %s", rid, type(exc).__name__)
            _fail(audit, manifest, run_dir, exc)
            if metrics:
                metrics.run_finished("failed")
            raise
        if metrics:
            metrics.run_finished("done")
        _publish(result, run_dir, audit, render or _default_renderer(chosen, settings), memory)
        return result
    finally:
        close = getattr(decider, "close", None)
        if callable(close):
            close()
        if built and prov is not None:
            prov.close()


def _publish(
    result: AssessmentResult,
    run_dir: Path,
    audit: AuditLog,
    render: Renderer,
    memory: MemoryStore | None,
) -> None:
    """Reports and memory come after the final manifest. The result is valid even if they fail
    (the manifest stays ``done``; ``vg report`` can render again), so a failure here is recorded
    as a ``post.failed`` event and re-raised, never as a failed run."""
    try:
        render(result, run_dir)
        if memory is not None:
            memory.save_assessment(result)
    except Exception as exc:
        log.error("run %s: reports or memory failed: %s", result.run_id, type(exc).__name__)
        _record_failure(audit, "post.failed", result.run_id, exc)
        raise


def _default_renderer(controls: ControlSet, settings: Settings) -> Renderer:
    """Write the formats listed in ``reporting.formats`` into the run folder."""

    def render(_result: AssessmentResult, run_dir: Path) -> None:
        render_reports(run_dir, controls, settings.reporting)

    return render


def _decider_names(settings: Settings) -> set[str]:
    d = settings.decision
    return {d.provider, d.jev.fallback_provider} if d.provider == "jev" else {d.provider}


def _context(
    settings: Settings,
    run_id: str,
    run_dir: Path,
    audit: AuditLog,
    prov: Providers,
    prompts: PromptLoader,
    decider: Decider,
) -> RunContext:
    llm, tracker, v = prov.llm, prov.tracker, settings.verification
    rules = settings.decision.rule
    return RunContext(
        settings=settings,
        run_id=run_id,
        run_dir=run_dir,
        audit=audit,
        decider=decider,
        embedder=prov.embedder,
        cost=tracker,
        intake=IntakeAgent(llm, prompts, audit, tracker, settings.intake),
        mapper=MapperAgent(llm, prompts, audit, tracker, v, rules),
        reviewer=ReviewerAgent(llm, prompts, audit, tracker, v, rules),
        reporter=ReporterAgent(llm, prompts, audit, tracker, settings.reporting),
        citation=CitationChecker(v),
    )


__all__ = ["Differ", "Renderer", "run_assessment"]
