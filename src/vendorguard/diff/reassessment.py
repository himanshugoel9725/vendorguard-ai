"""Re-assessment diff: what changed between a vendor's previous run and the new one."""

from collections.abc import Sequence
from decimal import Decimal

from vendorguard.interfaces.memory import MemoryStore
from vendorguard.models.finding import ControlFinding, ControlStatus
from vendorguard.models.run import AssessmentResult, ReassessmentDiff, StatusChange
from vendorguard.models.score import RiskScore

SCORE_DIGITS = Decimal("0.1")


def _statuses(findings: Sequence[ControlFinding]) -> dict[str, ControlStatus]:
    return {f.control_id: f.effective_status for f in findings}


def find_previous(memory: MemoryStore, vendor_id: str, run_id: str) -> AssessmentResult | None:
    """The run to diff against: the newest stored run of the vendor that comes BEFORE ``run_id``.

    A new run comes after everything stored. A run that is stored already (a re-run with the
    same deterministic ID) keeps its original place, so re-running year 1 after year 2 is still
    compared with the run before year 1, never with year 2.
    """
    history = memory.list_assessments(vendor_id)  # newest first
    own = next((a for a in history if a.run_id == run_id), None)
    for entry in history:
        if entry.run_id == run_id:
            continue
        if own is None or (entry.created_at, entry.run_id) < (own.created_at, own.run_id):
            return memory.get_assessment(entry.run_id)
    return None


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


__all__ = ["compute_diff", "find_previous"]
