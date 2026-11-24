"""One plain-data view of a run that the Markdown and HTML reports both render."""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import ControlSet
from vendorguard.models.run import AssessmentResult, RunManifest

STATUS_LABELS = {
    "met": "Met",
    "partial": "Partially met",
    "not_met": "Not met",
    "no_evidence": "No evidence",
    "needs_human_review": "Needs human review",
}


def audit_summary(events: Sequence[AuditEvent]) -> dict[str, Any]:
    """Counts only (no hashes, no times): steps per stage, tokens, spend, cache hits."""
    stages = Counter(e.stage for e in events)
    return {
        "events": len(events),
        "stages": dict(sorted(stages.items())),
        "tokens_in": sum(e.tokens_in for e in events),
        "tokens_out": sum(e.tokens_out for e in events),
        "usd": round(sum(e.usd for e in events), 6),
        "cached": sum(1 for e in events if e.cached),
        "fallbacks": sum(n for s, n in stages.items() if "fallback" in s),
    }


def _doc_names(manifest: RunManifest | None) -> dict[str, str]:
    return {i.sha256: i.filename for i in manifest.inputs} if manifest else {}


def _document(doc_id: str | None, names: dict[str, str]) -> str:
    if doc_id is None:
        return "unknown document"
    return next((n for sha, n in names.items() if sha.startswith(doc_id)), doc_id)


def build_view(
    result: AssessmentResult,
    controls: ControlSet,
    manifest: RunManifest | None = None,
    events: Sequence[AuditEvent] | None = None,
) -> dict[str, Any]:
    """Everything a report shows, with enums turned into plain strings."""
    by_id = {c.id: c for c in controls.controls}
    names = _doc_names(manifest)
    findings = []
    for f in result.findings:
        control = by_id.get(f.control_id)
        status = f.effective_status.value
        findings.append(
            {
                "id": f.control_id,
                "title": control.title if control else f.control_id,
                "domain": control.domain if control else "",
                "criticality": control.criticality.value if control else "",
                "status": status,
                "status_label": STATUS_LABELS[status],
                "system_status": f.status.value,
                "system_label": STATUS_LABELS[f.status.value],
                "rationale": f.rationale,
                "review_rounds": f.review_rounds,
                "override": (
                    {
                        "analyst": f.override.analyst,
                        "reason": f.override.reason,
                        "at": f.override.at.isoformat(),
                    }
                    if f.override
                    else None
                ),
                "citations": [
                    {"quote": c.quote, "document": _document(c.doc_id, names), "page": c.page}
                    for c in f.citations
                    if c.valid is not False
                ],
            }
        )
    counts = Counter(f["status"] for f in findings)
    p = result.profile
    return {
        "run_id": result.run_id,
        "vendor_id": result.vendor_id,
        "created_at": result.created_at.isoformat(),
        "vendor_name": p.vendor_name,
        "profile": {
            "services": p.services,
            "hosting": p.hosting,
            "certifications": p.certifications,
            "subprocessors": p.subprocessors,
            "data_categories": [d.value for d in p.data_categories],
            "report_period": p.report_period,
        },
        "summary": result.summary,
        "overall": result.score.overall,
        "band": result.score.band.value,
        "inherent_tier": result.inherent_risk.tier.value,
        "inherent_reasons": result.inherent_risk.reasons,
        "triggered_rules": result.score.triggered_rules,
        "domains": [
            {"code": code, "name": controls.domains.get(code, code), "score": score}
            for code, score in sorted(result.score.domain_scores.items())
        ],
        "counts": [
            {"label": STATUS_LABELS[k], "key": k, "n": counts.get(k, 0)} for k in STATUS_LABELS
        ],
        "findings": findings,
        "diff": result.diff.model_dump(mode="json") if result.diff else None,
        "overrides": [f for f in findings if f["override"]],
        "cost": result.cost.model_dump(mode="json"),
        "audit": audit_summary(events) if events is not None else None,
        "manifest": manifest.model_dump(mode="json") if manifest else None,
    }


__all__ = ["STATUS_LABELS", "audit_summary", "build_view"]
