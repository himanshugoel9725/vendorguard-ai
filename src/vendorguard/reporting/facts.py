"""The structured facts the Reporter Agent may talk about (and the number guard checks against)."""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from vendorguard.models.finding import ControlFinding, ControlStatus
from vendorguard.models.run import ReassessmentDiff
from vendorguard.models.score import InherentRisk, RiskScore


def build_facts(
    vendor_name: str,
    inherent: InherentRisk,
    score: RiskScore,
    findings: Sequence[ControlFinding],
    diff: ReassessmentDiff | None = None,
) -> dict[str, Any]:
    """Plain JSON-able facts. ``gaps`` = controls whose effective status is not ``met``, sorted."""
    statuses = {f.control_id: f.effective_status for f in findings}
    counts = Counter(s.value for s in statuses.values())
    facts: dict[str, Any] = {
        "vendor_name": vendor_name,
        "overall": score.overall,
        "band": score.band.value,
        "inherent_tier": inherent.tier.value,
        "counts": {s.value: counts.get(s.value, 0) for s in ControlStatus},
        "gaps": sorted(c for c, s in statuses.items() if s is not ControlStatus.MET),
        "domain_scores": dict(sorted(score.domain_scores.items())),
        "triggered_rules": list(score.triggered_rules),
    }
    if diff is not None:
        facts["diff"] = {
            "new_gaps": sorted(diff.new_gaps),
            "resolved_gaps": sorted(diff.resolved_gaps),
            "score_delta": diff.score_delta,
        }
    return facts


__all__ = ["build_facts"]
