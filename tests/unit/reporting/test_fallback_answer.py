"""The template answer of the Ask agent (also the mock LLM's answer)."""

from typing import Any

from vendorguard.models.outputs import AskOutput
from vendorguard.reporting.fallback_answer import fallback_answer
from vendorguard.verification.answer_guard import check_answer


def _run(rid: str, overall: float, findings: dict[str, str], band: str = "high") -> dict[str, Any]:
    return {"run_id": rid, "overall": overall, "band": band, "findings": findings}


NEW = _run("run_new", 30.5, {"IAM-04": "met", "OPS-02": "not_met", "DAT-01": "partial"}, "medium")
OLD = _run("run_old", 40.0, {"IAM-04": "not_met", "OPS-02": "met", "DAT-01": "partial"})


def test_no_runs() -> None:
    out = fallback_answer("anything", [])
    assert out == {
        "text": "No assessments are stored for this vendor.",
        "cited_run_ids": [],
        "cited_control_ids": [],
    }


def test_change_question_with_two_runs() -> None:
    out = fallback_answer("What changed?", [NEW, OLD])
    assert out["cited_run_ids"] == ["run_new", "run_old"]
    assert out["cited_control_ids"] == ["OPS-02", "IAM-04"]  # new gaps, then resolved
    assert "from 40 to 30.5" in out["text"]
    assert "New gaps: OPS-02." in out["text"] and "Resolved gaps: IAM-04." in out["text"]


def test_change_question_with_one_run_falls_to_default() -> None:
    out = fallback_answer("what changed?", [NEW])
    assert out["text"].startswith("Latest run run_new")


def test_no_changes_says_none() -> None:
    out = fallback_answer("any difference since last time?", [NEW, NEW])
    assert "New gaps: none. Resolved gaps: none." in out["text"]
    assert out["cited_control_ids"] == []


def test_asked_control() -> None:
    out = fallback_answer("How is OPS-02 and ZZZ-01 and IAM-04?", [NEW, OLD])
    assert out["text"] == "IAM-04 is met in run run_new. OPS-02 is not_met in run run_new."
    assert out["cited_control_ids"] == ["IAM-04", "OPS-02"]
    assert out["cited_run_ids"] == ["run_new"]


def test_asked_control_in_lowercase_is_not_matched() -> None:
    assert fallback_answer("about iam-04?", [NEW])["text"].startswith("Latest run")


def test_default_gaps_summary() -> None:
    out = fallback_answer("Give me an overview", [NEW, OLD])
    assert out["text"] == "Latest run run_new: overall score 30.5 (medium). Gaps: DAT-01, OPS-02."
    assert out["cited_control_ids"] == ["DAT-01", "OPS-02"]


def test_all_met_gaps_none() -> None:
    out = fallback_answer("overview", [_run("r1", 0.0, {"IAM-04": "met"}, "low")])
    assert out["text"].endswith("Gaps: none.") and out["cited_control_ids"] == []


def test_needs_human_review_counts_as_gap() -> None:
    out = fallback_answer("overview", [_run("r1", 5.0, {"IAM-04": "needs_human_review"})])
    assert out["cited_control_ids"] == ["IAM-04"]


def test_output_is_valid_and_passes_the_guard() -> None:
    runs = [NEW, OLD]
    for q in ("What changed?", "IAM-04?", "overview", "x"):
        out = AskOutput.model_validate(fallback_answer(q, runs))
        assert check_answer(out, ["run_new", "run_old"], ["IAM-04", "OPS-02", "DAT-01"]) == []


def test_deterministic_and_does_not_mutate() -> None:
    runs = [NEW, OLD]
    before = repr(runs)
    assert fallback_answer("What changed?", runs) == fallback_answer("What changed?", runs)
    assert repr(runs) == before
