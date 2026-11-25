"""Evaluation metrics: findings versus golden labels (pure functions, no I/O, no rounding).

Predictions are the system's own ``status`` (analyst overrides are not part of an evaluation).
``needs_human_review`` is a prediction column that is never right: it counts against accuracy and
recall, but belongs to no golden class, so it is not a precision/F1 class of its own.
"""

from collections.abc import Mapping, Sequence

from vendorguard.errors import ConfigError
from vendorguard.models._base import ContractModel
from vendorguard.models.decision import DecisionLabel, Gate
from vendorguard.models.finding import ControlFinding, ControlStatus, DraftStatus

GOLD_LABELS: tuple[str, ...] = tuple(s.value for s in DraftStatus)
PRED_LABELS: tuple[str, ...] = tuple(s.value for s in ControlStatus)


class ClassMetrics(ContractModel):
    """Precision, recall and F1 of one golden status; ``support`` = golden count."""

    precision: float
    recall: float
    f1: float
    support: int


class EvalMetrics(ContractModel):
    """Everything measured for one run against its golden file."""

    controls: int
    accuracy: float
    macro_f1: float
    per_status: dict[str, ClassMetrics]
    confusion: dict[str, dict[str, int]]  # confusion[golden][predicted]
    citation_validity_rate: float | None  # None when no finding cites anything
    human_review_rate: float
    triage_skip_rate: float


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def confusion_matrix(
    golden: Mapping[str, str], predicted: Mapping[str, str]
) -> dict[str, dict[str, int]]:
    """Counts per (golden, predicted) over the controls in ``predicted``; all cells present."""
    unknown = sorted(set(predicted) - set(golden))
    if unknown:
        raise ConfigError(f"findings for controls without a golden label: {', '.join(unknown)}")
    matrix = {g: dict.fromkeys(PRED_LABELS, 0) for g in GOLD_LABELS}
    for cid, status in predicted.items():
        matrix[str(golden[cid])][str(status)] += 1
    return matrix


def per_status_metrics(matrix: Mapping[str, Mapping[str, int]]) -> dict[str, ClassMetrics]:
    """Precision, recall, F1 and support for each golden status."""
    out: dict[str, ClassMetrics] = {}
    for label in GOLD_LABELS:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted = sum(matrix[g][label] for g in GOLD_LABELS)
        precision, recall = _ratio(tp, predicted), _ratio(tp, support)
        f1 = _ratio(2 * tp, predicted + support)  # = 2PR/(P+R) without the zero-division cases
        out[label] = ClassMetrics(precision=precision, recall=recall, f1=f1, support=support)
    return out


def macro_f1(matrix: Mapping[str, Mapping[str, int]]) -> float:
    """Mean F1 over the statuses that exist in the golden labels or in the predictions."""
    classes = per_status_metrics(matrix)
    used = [
        m.f1
        for label, m in classes.items()
        if m.support or sum(matrix[g][label] for g in GOLD_LABELS)
    ]
    return sum(used) / len(used) if used else 0.0


def citation_validity_rate(findings: Sequence[ControlFinding]) -> float | None:
    """Share of checked citations that are valid (a relocated quote is valid); None if none."""
    checked = [c.valid for f in findings for c in f.citations if c.valid is not None]
    return _ratio(sum(checked), len(checked)) if checked else None


def was_skipped_by_triage(finding: ControlFinding) -> bool:
    """True if triage said 'not addressed' with enough confidence to skip the model call:
    the cascade then never reached the citation gate."""
    gates = {t.gate for t in finding.trace}
    triaged = any(
        t.gate is Gate.TRIAGE and t.decision.label is DecisionLabel.NOT_ADDRESSED
        for t in finding.trace
    )
    return triaged and Gate.CITATION not in gates


def evaluate(findings: Sequence[ControlFinding], golden: Mapping[str, str]) -> EvalMetrics:
    """Score ``findings`` against ``golden`` (control id -> status). Controls without a finding
    (subset runs) are not counted; a finding without a golden label is a ConfigError."""
    if not findings:
        raise ConfigError("nothing to evaluate: no findings")
    predicted = {f.control_id: f.status.value for f in findings}
    if len(predicted) != len(findings):
        raise ConfigError("duplicate control ids in the findings")
    matrix = confusion_matrix(golden, predicted)
    total = len(findings)
    correct = sum(matrix[label][label] for label in GOLD_LABELS)
    return EvalMetrics(
        controls=total,
        accuracy=correct / total,
        macro_f1=macro_f1(matrix),
        per_status=per_status_metrics(matrix),
        confusion=matrix,
        citation_validity_rate=citation_validity_rate(findings),
        human_review_rate=_ratio(
            sum(f.status is ControlStatus.NEEDS_HUMAN_REVIEW for f in findings), total
        ),
        triage_skip_rate=_ratio(sum(was_skipped_by_triage(f) for f in findings), total),
    )


__all__ = [
    "ClassMetrics",
    "EvalMetrics",
    "citation_validity_rate",
    "confusion_matrix",
    "evaluate",
    "macro_f1",
    "per_status_metrics",
    "was_skipped_by_triage",
]
