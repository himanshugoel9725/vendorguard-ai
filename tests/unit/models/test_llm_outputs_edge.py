"""Edge cases of the LLM contracts and the output schemas."""

import pytest
from pydantic import BaseModel, ValidationError

from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.models.outputs import (
    MAX_CITED_IDS,
    MAX_REASON_CHARS,
    AskOutput,
    JudgeOutput,
    SummaryOutput,
)


class Inner(BaseModel):
    names: list[str]


class Outer(BaseModel):
    inner: Inner
    score: float


def test_chat_message_keeps_unicode_and_newlines() -> None:
    text = "Zürich\n\t☃ \U0001f600\r\n"
    assert ChatMessage(role="user", content=text).content == text
    assert ChatMessage(role="system", content="").content == ""


def test_usage_accepts_huge_ints_and_rejects_negatives() -> None:
    assert Usage(tokens_in=10**18, tokens_out=10**30).tokens_out == 10**30
    with pytest.raises(ValidationError):
        Usage(tokens_in=-1)


def test_llm_result_generic_round_trips_through_json() -> None:
    result = LLMResult[Outer](
        parsed=Outer(inner=Inner(names=["Zürich", "b"]), score=0.5),
        usage=Usage(tokens_in=3, tokens_out=4),
        provider="p",
        model="m",
        cached=True,
        latency_ms=12.5,
    )
    again = LLMResult[Outer].model_validate_json(result.model_dump_json())
    assert again == result and again.cached is True and again.latency_ms == 12.5
    assert again.parsed.inner.names == ["Zürich", "b"]
    with pytest.raises(ValidationError):
        LLMResult[Outer].model_validate({**result.model_dump(), "parsed": {"inner": 1}})
    with pytest.raises(ValidationError):
        LLMResult[Outer].model_validate({**result.model_dump(), "provider": " "})


@pytest.mark.parametrize("model", [JudgeOutput, SummaryOutput, AskOutput])
def test_schemas_forbid_additional_properties(model: type[BaseModel]) -> None:
    assert model.model_json_schema()["additionalProperties"] is False


def test_documented_bounds_are_in_the_json_schema() -> None:
    judge = JudgeOutput.model_json_schema()["properties"]
    assert judge["reason"]["maxLength"] == MAX_REASON_CHARS
    assert (judge["confidence"]["minimum"], judge["confidence"]["maximum"]) == (0.0, 1.0)
    ask = AskOutput.model_json_schema()["properties"]
    assert ask["cited_run_ids"]["maxItems"] == MAX_CITED_IDS
    assert ask["cited_control_ids"]["maxItems"] == MAX_CITED_IDS
    assert SummaryOutput.model_json_schema()["properties"]["summary"]["minLength"] == 1


def test_ask_output_enforces_max_items_and_unicode_text() -> None:
    ok = AskOutput(text="Zürich ☃", cited_run_ids=["r"] * MAX_CITED_IDS, cited_control_ids=[])
    assert ok.text == "Zürich ☃"
    with pytest.raises(ValidationError):
        AskOutput(text="t", cited_run_ids=["r"] * (MAX_CITED_IDS + 1), cited_control_ids=[])
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate({"label": "addressed", "confidence": 0.5, "extra": 1})
    assert SummaryOutput(summary="é" * 5000).summary.startswith("é")
