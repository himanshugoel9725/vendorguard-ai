"""Mock reporter and ask agents: number formatting, citations and the newest-two-runs rule."""

from collections.abc import Callable
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.errors import SchemaValidationError
from vendorguard.models.outputs import AskOutput, SummaryOutput
from vendorguard.providers.llm.mock import MockLLM


@pytest.fixture
def settings(settings_override: Callable[..., Settings]) -> Settings:
    return settings_override()


@pytest.fixture
def mock(settings: Settings) -> MockLLM:
    return MockLLM(settings.decision.rule)


# --- reporter ------------------------------------------------------------------------------------


def _summary(mock: MockLLM, **facts: Any) -> str:
    base = {"vendor_name": "Acme", "overall": 12.0, "band": "low", "counts": {"met": 3}, "gaps": []}
    hints = {**base, **facts}
    return mock.complete_json([], SummaryOutput, purpose="reporter", hints=hints).parsed.summary


def test_reporter_number_formatting_and_missing_counts(mock: MockLLM) -> None:
    text = _summary(mock)
    assert "score is 12 (low)" in text and "12.0" not in text
    assert "Of 3 controls, 3 are met, 0 partially met, 0 not met, 0 without" in text
    assert "no open gaps" in text
    assert "score is 41.25" in _summary(mock, overall=41.25)


def test_reporter_many_gaps_sorted_and_missing_gaps_key(mock: MockLLM) -> None:
    ids = [f"CTL-{n:02d}" for n in range(30, 0, -1)]
    text = _summary(mock, gaps=ids)
    assert f"Open gaps: {', '.join(sorted(ids))}." in text
    hints = {"vendor_name": "A", "overall": 1, "band": "low", "counts": {}}
    out = mock.complete_json([], SummaryOutput, purpose="reporter", hints=hints).parsed
    assert "Of 0 controls" in out.summary


# --- ask -----------------------------------------------------------------------------------------


def _run(run_id: str, overall: float, findings: dict[str, str]) -> dict[str, Any]:
    return {"run_id": run_id, "overall": overall, "band": "low", "findings": findings}


def _ask(mock: MockLLM, question: str, runs: list[dict[str, Any]]) -> AskOutput:
    hints = {"question": question, "runs": runs}
    return mock.complete_json([], AskOutput, purpose="ask", hints=hints).parsed


def test_ask_without_runs(mock: MockLLM) -> None:
    out = _ask(mock, "anything", [])
    assert out.cited_run_ids == [] and "No assessments" in out.text


def test_ask_lowercase_and_unknown_ids_are_ignored(mock: MockLLM) -> None:
    runs = [_run("r2", 10.0, {"IAM-02": "met", "BCK-01": "not_met"})]
    out = _ask(mock, "what about iam-02 and ZZZ-99?", runs)
    assert out.cited_control_ids == ["BCK-01"]  # falls through to the gap list
    assert _ask(mock, "IAM-02 please", runs).text == "IAM-02 is met in run r2."


def test_ask_ids_only_in_older_run_are_not_cited(mock: MockLLM) -> None:
    runs = [_run("r2", 10.0, {"IAM-02": "met"}), _run("r1", 20.0, {"OLD-01": "met"})]
    out = _ask(mock, "tell me about OLD-01", runs)
    assert out.cited_control_ids == [] and out.cited_run_ids == ["r2"]


def test_ask_change_words_need_two_runs(mock: MockLLM) -> None:
    out = _ask(mock, "what changed?", [_run("r2", 10.0, {"IAM-02": "not_met"})])
    assert out.cited_run_ids == ["r2"] and out.cited_control_ids == ["IAM-02"]


def test_ask_compares_only_the_two_newest_runs(mock: MockLLM) -> None:
    runs = [
        _run("r3", 10.5, {"A-01": "met", "IAM-02": "partial"}),
        _run("r2", 30.0, {"IAM-02": "not_met", "BCK-01": "partial"}),
        _run("r1", 99.0, {"ZZZ-09": "not_met"}),
    ]
    out = _ask(mock, "What has changed since the last run?", runs)
    assert out.cited_run_ids == ["r3", "r2"]
    assert out.cited_control_ids == ["BCK-01"]  # no new gaps, BCK-01 resolved
    assert "from 30 to 10.5" in out.text and "ZZZ-09" not in out.text


def test_ask_needs_human_review_counts_as_gap(mock: MockLLM) -> None:
    runs = [_run("r2", 5.0, {"IAM-02": "needs_human_review", "BCK-01": "met"})]
    assert _ask(mock, "summary?", runs).cited_control_ids == ["IAM-02"]


def test_ask_many_gaps_exceed_the_cited_id_limit(mock: MockLLM) -> None:
    """Documents current behaviour: more than 30 gaps cannot fit AskOutput."""
    findings = {f"CTL-{n:02d}": "not_met" for n in range(31)}
    with pytest.raises(SchemaValidationError):
        _ask(mock, "summary?", [_run("r1", 1.0, findings)])
