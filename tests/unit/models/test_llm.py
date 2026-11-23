"""LLM data contracts."""

import pytest
from pydantic import BaseModel, ValidationError

from vendorguard.models.llm import ChatMessage, LLMResult, Usage


class Answer(BaseModel):
    text: str


def test_chat_message_roles_are_limited() -> None:
    for role in ("system", "user", "assistant"):
        assert ChatMessage(role=role, content="x").role == role  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ChatMessage(role="tool", content="x")  # type: ignore[arg-type]


def test_chat_message_allows_empty_content_but_not_unknown_fields() -> None:
    assert ChatMessage(role="user", content="").content == ""
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="x", name="n")  # type: ignore[call-arg]


def test_usage_defaults_to_zero_and_rejects_negative_counts() -> None:
    assert Usage() == Usage(tokens_in=0, tokens_out=0)
    with pytest.raises(ValidationError):
        Usage(tokens_in=-1)
    with pytest.raises(ValidationError):
        Usage(tokens_out=-1)


def test_models_are_frozen() -> None:
    usage = Usage(tokens_in=3, tokens_out=4)
    with pytest.raises(ValidationError):
        usage.tokens_in = 9  # type: ignore[misc]


def test_llm_result_wraps_a_validated_output_with_its_provenance() -> None:
    result = LLMResult[Answer](
        parsed=Answer(text="ok"),
        usage=Usage(tokens_in=10, tokens_out=2),
        provider="ollama",
        model="m",
    )
    assert result.parsed.text == "ok" and result.cached is False and result.latency_ms == 0.0
    assert LLMResult[Answer].model_validate_json(result.model_dump_json()) == result


def test_llm_result_validates_the_parsed_type_and_names() -> None:
    with pytest.raises(ValidationError):
        LLMResult[Answer](parsed={"text": 5}, usage=Usage(), provider="p", model="m")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        LLMResult[Answer](parsed=Answer(text="a"), usage=Usage(), provider=" ", model="m")
    with pytest.raises(ValidationError):
        LLMResult[Answer](parsed=Answer(text="a"), usage=Usage(), provider="p", model="")
