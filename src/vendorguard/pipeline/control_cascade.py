"""The per-control cascade (PLAN 3.3): triage -> map -> citation -> verify -> review loop."""

from vendorguard.errors import DeciderError, LLMError, SchemaValidationError
from vendorguard.models.control import Control
from vendorguard.models.decision import Decision, DecisionLabel, Gate, GateTrace
from vendorguard.models.evidence import Citation, DraftCitation
from vendorguard.models.finding import MAX_CITATIONS, ControlFinding, ControlStatus, DraftFinding
from vendorguard.pipeline.context import RunContext
from vendorguard.pipeline.retrieval_plan import ControlEvidence
from vendorguard.utils.hashing import hash_obj

NO_EVIDENCE_RATIONALE = "The triage gate found no text about this control in the documents."
HUMAN_PREFIX = "Needs human review: "
RECOVERABLE = (LLMError, SchemaValidationError, DeciderError)


def _gate(
    ctx: RunContext,
    control: Control,
    trace: list[GateTrace],
    gate: Gate,
    decision: Decision,
    rnd: int,
    chunk_ids: list[str],
) -> None:
    """Append one GateTrace and write its audit event."""
    trace.append(GateTrace(gate=gate, decision=decision, round=rnd))
    ctx.audit.record(
        stage=f"gate.{gate.value}",
        actor=decision.provider,
        control_id=control.id,
        input_hash=hash_obj({"control": control.id, "round": rnd, "chunks": chunk_ids}),
        output_hash=hash_obj(decision.model_dump(mode="json")),
        decision=decision,
        tokens_in=0,
        tokens_out=0,
        usd=0.0,
        latency_ms=0.0,
        cached=False,
    )


def _done(ctx: RunContext, finding: ControlFinding) -> ControlFinding:
    """Write the closing event of a control's cascade and return the finding."""
    ctx.audit.record(
        stage="cascade.finding",
        actor="python",
        control_id=finding.control_id,
        input_hash=hash_obj({"control": finding.control_id, "gates": len(finding.trace)}),
        output_hash=hash_obj(finding.model_dump(mode="json")),
        tokens_in=0,
        tokens_out=0,
        usd=0.0,
        latency_ms=0.0,
        cached=False,
    )
    return finding


def _human(
    control: Control,
    trace: list[GateTrace],
    reason: str,
    citations: list[Citation],
) -> ControlFinding:
    valid = [c for c in citations if c.valid][:MAX_CITATIONS]
    return ControlFinding(
        control_id=control.id,
        status=ControlStatus.NEEDS_HUMAN_REVIEW,
        citations=valid,
        rationale=HUMAN_PREFIX + reason,
        trace=trace,
        review_rounds=sum(1 for t in trace if t.gate is Gate.REVIEW),
    )


def _cascade(
    ctx: RunContext, control: Control, ev: ControlEvidence, trace: list[GateTrace]
) -> ControlFinding:
    s = ctx.settings
    ids_top = [h.chunk.chunk_id for h in ev.top]
    if s.pipeline.triage_enabled:
        d = ctx.decider.triage(control, ev.top)
        _gate(ctx, control, trace, Gate.TRIAGE, d, 0, ids_top)
        if d.label is DecisionLabel.NOT_ADDRESSED and d.confidence >= s.decision.triage_threshold:
            return ControlFinding(
                control_id=control.id,
                status=ControlStatus.NO_EVIDENCE,
                citations=[],
                rationale=NO_EVIDENCE_RATIONALE,
                trace=trace,
                review_rounds=0,
            )
    draft = ctx.mapper.map(control, ev.top)
    flags: list[str] = []
    checked: list[Citation] = []
    for rnd in range(s.pipeline.max_review_rounds + 1):
        seen = ev.top if rnd == 0 else ev.wide
        chunks = [h.chunk for h in seen]
        report = ctx.citation.check(draft.status, draft.citations, chunks)
        checked = report.citations
        cite = Decision(
            label=DecisionLabel.SUPPORTED if report.ok else DecisionLabel.UNSUPPORTED,
            confidence=1.0,
            provider="citation_check",
            reason="; ".join(report.problems) or None,
        )
        _gate(ctx, control, trace, Gate.CITATION, cite, rnd, [c.chunk_id for c in chunks])
        if report.ok:
            # Verify the quotes as checked: fuzzy matches carry the source words (ADR / 5.12).
            verified = DraftFinding(
                status=draft.status,
                citations=[DraftCitation(chunk_id=c.chunk_id, quote=c.quote) for c in checked],
                rationale=draft.rationale,
            )
            v = ctx.decider.verify(control, verified, seen)
            _gate(ctx, control, trace, Gate.VERIFY, v, rnd, [c.chunk_id for c in chunks])
            if v.label is DecisionLabel.SUPPORTED and v.confidence >= s.decision.verify_threshold:
                return ControlFinding(
                    control_id=control.id,
                    status=ControlStatus(draft.status.value),
                    citations=checked,
                    rationale=draft.rationale,
                    trace=trace,
                    review_rounds=rnd,
                )
            flags = [v.reason or "the verify gate did not support the status"]
        else:
            flags = list(report.problems)
        if rnd < s.pipeline.max_review_rounds:
            draft = ctx.reviewer.review(control, draft, flags, ev.wide)
            note = Decision(
                label=DecisionLabel.ADDRESSED,
                confidence=1.0,
                provider="reviewer",
                reason=f"revised to {draft.status.value}",
            )
            _gate(
                ctx, control, trace, Gate.REVIEW, note, rnd + 1, [h.chunk.chunk_id for h in ev.wide]
            )
    return _human(control, trace, "; ".join(flags), checked)


def run_cascade(ctx: RunContext, control: Control, ev: ControlEvidence) -> ControlFinding:
    """The finding of one control. A model or schema failure becomes ``needs_human_review``;
    a budget, cache-miss or config error propagates and aborts the run."""
    trace: list[GateTrace] = []
    try:
        finding = _cascade(ctx, control, ev, trace)
    except RECOVERABLE as exc:
        reason = f"automatic review failed ({type(exc).__name__})"
        finding = _human(control, trace, reason, [])
    return _done(ctx, finding)


__all__ = ["run_cascade"]
