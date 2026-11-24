"""Re-assessment diff: what changed between a vendor's previous run and the new one."""

from collections.abc import Sequence
from decimal import Decimal

from vendorguard.models.finding import ControlFinding, ControlStatus
from vendorguard.models.run import AssessmentResult, ReassessmentDiff, StatusChange
from vendorguard.models.score import RiskScore

SCORE_DIGITS = Decimal("0.1")


def _statuses(findings: Sequence[ControlFinding]) -> dict[str, ControlStatus]:
    return {f.control_id: f.effective_status for f in findings}


def compute_diff(
    findings: Sequence[ControlFinding], score: RiskScore, previous: AssessmentResult
) -> ReassessmentDiff:
    """Compare the new findings with the previous result (pure; analyst overrides count).

    A *gap* is a control whose effective status is not ``met`` (the definition of
    ``reporting.facts``). Only controls assessed in BOTH runs are compared, so a subset run
    never invents changes: ``new_gaps`` were met before and are not now, ``resolved_gaps`` were
    gaps before and are met now, ``changed`` lists every other status change, all sorted by
    control ID. ``score_delta`` is new minus previous, exact to one decimal.
    """
    before, after = _statuses(previous.findings), _statuses(findings)
    common = sorted(before.keys() & after.keys())
    met = ControlStatus.MET
    return ReassessmentDiff(
        previous_run_id=previous.run_id,
        new_gaps=[c for c in common if before[c] is met and after[c] is not met],
        resolved_gaps=[c for c in common if before[c] is not met and after[c] is met],
        changed=[
            StatusChange(control_id=c, from_status=before[c], to_status=after[c])
            for c in common
            if before[c] is not after[c]
        ],
        score_delta=float(
            (Decimal(str(score.overall)) - Decimal(str(previous.score.overall))).quantize(
                SCORE_DIGITS
            )
        ),
    )


__all__ = ["compute_diff"]
