"""LLM output schemas of the judge, reporter and ask agents."""

import pytest
from pydantic import ValidationError

from vendorguard.models.decision import DecisionLabel
from vendorguard.models.outputs import (
    MAX_CITED_IDS,
    MAX_REASON_CHARS,
    AskOutput,
    JudgeOutput,
    SummaryOutput,
)


def test_judge_output_bounds() -> None:
    assert JudgeOutput(label=DecisionLabel.SUPPORTED, confidence=1.0).reason == ""
    JudgeOutput(label="addressed", confidence=0.0, reason="x" * MAX_REASON_CHARS)  # type: ignore[arg-type]
    for bad in (
        dict(label="maybe", confidence=0.5),
        dict(label="supported", confidence=1.5),
        dict(label="supported", confidence=0.5, reason="x" * (MAX_REASON_CHARS + 1)),
    ):
        with pytest.raises(ValidationError):
            JudgeOutput(**bad)  # type: ignore[arg-type]


def test_summary_output_needs_text() -> None:
    assert SummaryOutput(summary="ok").summary == "ok"
    for bad in ("", "   "):
        with pytest.raises(ValidationError):
            SummaryOutput(summary=bad)


def test_ask_output_bounds() -> None:
    AskOutput(text="t", cited_run_ids=["r"] * MAX_CITED_IDS, cited_control_ids=[])
    with pytest.raises(ValidationError):
        AskOutput(text="t", cited_run_ids=["r"] * (MAX_CITED_IDS + 1), cited_control_ids=[])
    with pytest.raises(ValidationError):
        AskOutput(text="", cited_run_ids=[], cited_control_ids=[])


def test_schemas_export_and_forbid_extra_fields() -> None:
    for model in (JudgeOutput, SummaryOutput, AskOutput):
        assert model.model_json_schema()["additionalProperties"] is False
