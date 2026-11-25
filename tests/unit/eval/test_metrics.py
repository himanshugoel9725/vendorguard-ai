"""Evaluation metrics: hand-computed cases."""

import pytest

from vendorguard.errors import ConfigError
from vendorguard.eval.metrics import (
    citation_validity_rate,
    confusion_matrix,
    evaluate,
    macro_f1,
    per_status_metrics,
    was_skipped_by_triage,
)
from vendorguard.models.decision import Decision, DecisionLabel, Gate, GateTrace
from vendorguard.models.evidence import Citation
from vendorguard.models.finding import ControlFinding, ControlStatus


def _decision(label: DecisionLabel, conf: float = 0.9) -> Decision:
    return Decision(label=label, confidence=conf, provider="rule")


def _finding(
    cid: str,
    status: str,
    *,
    trace: list[GateTrace] | None = None,
    valid: list[bool] | None = None,
) -> ControlFinding:
    cites = [Citation(chunk_id="c", quote=f"q{i}", valid=v) for i, v in enumerate(valid or [])]
    return ControlFinding(
        control_id=cid,
        status=ControlStatus(status),
        citations=cites,
        rationale="r",
        trace=trace or [],
        review_rounds=0,
    )


GOLD = {"A-01": "met", "A-02": "met", "A-03": "not_met", "A-04": "no_evidence"}


def test_perfect_run() -> None:
    m = evaluate([_finding(c, s) for c, s in GOLD.items()], GOLD)
    assert m.accuracy == 1.0 and m.macro_f1 == 1.0
    assert m.human_review_rate == 0.0 and m.triage_skip_rate == 0.0
    assert m.citation_validity_rate is None
    assert m.per_status["met"].support == 2 and m.per_status["partial"].support == 0


def test_hand_computed_confusion_and_f1() -> None:
    pred = {"A-01": "met", "A-02": "not_met", "A-03": "not_met", "A-04": "needs_human_review"}
    m = evaluate([_finding(c, s) for c, s in pred.items()], GOLD)
    assert m.accuracy == 0.5
    assert m.confusion["met"]["not_met"] == 1
    assert m.confusion["no_evidence"]["needs_human_review"] == 1
    met, not_met = m.per_status["met"], m.per_status["not_met"]
    assert (met.precision, met.recall) == (1.0, 0.5)
    assert (not_met.precision, not_met.recall) == (0.5, 1.0)
    assert met.f1 == pytest.approx(2 / 3) and not_met.f1 == pytest.approx(2 / 3)
    assert m.per_status["no_evidence"].f1 == 0.0
    # classes in play: met, not_met, no_evidence (partial has no support and no predictions)
    assert m.macro_f1 == pytest.approx((2 / 3 + 2 / 3 + 0) / 3)
    assert m.human_review_rate == 0.25


def test_class_predicted_but_absent_from_gold_counts_in_macro() -> None:
    matrix = confusion_matrix({"A-01": "met"}, {"A-01": "partial"})
    assert per_status_metrics(matrix)["partial"].precision == 0.0
    assert macro_f1(matrix) == 0.0  # met (missed) and partial (wrong) are both 0


def test_subset_runs_only_count_assessed_controls() -> None:
    m = evaluate([_finding("A-01", "met")], GOLD)
    assert m.controls == 1 and m.accuracy == 1.0


def test_errors() -> None:
    with pytest.raises(ConfigError):
        evaluate([], GOLD)
    with pytest.raises(ConfigError, match="Z-99"):
        evaluate([_finding("Z-99", "met")], GOLD)
    with pytest.raises(ConfigError, match="duplicate"):
        evaluate([_finding("A-01", "met"), _finding("A-01", "met")], GOLD)


def test_citation_validity_rate() -> None:
    fs = [_finding("A-01", "met", valid=[True, True]), _finding("A-02", "met", valid=[False])]
    assert citation_validity_rate(fs) == pytest.approx(2 / 3)
    assert citation_validity_rate([_finding("A-01", "met")]) is None


def test_triage_skip_detection() -> None:
    skip = [GateTrace(gate=Gate.TRIAGE, decision=_decision(DecisionLabel.NOT_ADDRESSED), round=0)]
    went_on = [
        *skip,
        GateTrace(gate=Gate.CITATION, decision=_decision(DecisionLabel.SUPPORTED), round=0),
    ]
    addressed = [GateTrace(gate=Gate.TRIAGE, decision=_decision(DecisionLabel.ADDRESSED), round=0)]
    assert was_skipped_by_triage(_finding("A-01", "no_evidence", trace=skip))
    assert not was_skipped_by_triage(_finding("A-01", "met", trace=went_on))
    assert not was_skipped_by_triage(_finding("A-01", "met", trace=addressed))
    assert not was_skipped_by_triage(_finding("A-01", "met"))
    m = evaluate([_finding("A-01", "no_evidence", trace=skip), _finding("A-02", "met")], GOLD)
    assert m.triage_skip_rate == 0.5
