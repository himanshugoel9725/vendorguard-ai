"""Edge cases of the shared JSON helpers and the HTTP retry helper."""

from collections.abc import Sequence

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from vendorguard.errors import LLMError, SchemaValidationError
from vendorguard.models.llm import ChatMessage, Usage
from vendorguard.providers.llm._http import post_json, retry_after_seconds
from vendorguard.providers.llm._json import (
    complete_with_repair,
    describe_problem,
    extract_json,
    repair_messages,
)

MSGS = [ChatMessage(role="user", content="q")]


class Inner(BaseModel):
    n: int


class Outer(BaseModel):
    items: list[Inner]
    name: str


def test_extract_json_edges() -> None:
    assert extract_json("") == ""
    assert extract_json('  {"a": 1}\n') == '{"a": 1}'
    assert extract_json('```JSON\n{"a": 1}\n```') == '{"a": 1}'
    # prose around the fence is not stripped: the fence regex is anchored
    assert extract_json('Here:\n```json\n{"a": 1}\n```') == 'Here:\n```json\n{"a": 1}\n```'
    assert extract_json('```json\n{"a": "```"}\n```') == '{"a": "```"}'


def test_describe_problem_uses_nested_paths_and_hides_values() -> None:
    with pytest.raises(ValidationError) as info:
        Outer.model_validate({"items": [{"n": "SECRET"}], "name": 3})
    text = describe_problem(info.value)
    assert "items.0.n" in text and "name" in text and "SECRET" not in text
    assert text == describe_problem(info.value)


def test_repair_messages_keeps_original_and_appends_two() -> None:
    out = repair_messages(MSGS, "bad", "x: y")
    assert out[0] == MSGS[0] and [m.role for m in out] == ["user", "assistant", "user"]
    assert out[1].content == "bad" and "x: y" in out[2].content


def test_sender_exception_propagates_unchanged() -> None:
    def send(_: Sequence[ChatMessage]) -> tuple[str, Usage]:
        raise LLMError("down")

    with pytest.raises(LLMError, match="down"):
        complete_with_repair(send, MSGS, Inner, 2)


def test_zero_repair_attempts_fails_after_one_call() -> None:
    calls: list[int] = []

    def send(_: Sequence[ChatMessage]) -> tuple[str, Usage]:
        calls.append(1)
        return "{}", Usage(tokens_in=1, tokens_out=1)

    with pytest.raises(SchemaValidationError, match="1 attempt"):
        complete_with_repair(send, MSGS, Inner, 0)
    assert len(calls) == 1


def test_repair_conversation_grows_each_attempt() -> None:
    seen: list[int] = []

    def send(conv: Sequence[ChatMessage]) -> tuple[str, Usage]:
        seen.append(len(conv))
        return ('{"n": 1}' if len(seen) == 3 else "x"), Usage(tokens_in=2, tokens_out=1)

    parsed, usage = complete_with_repair(send, MSGS, Inner, 2)
    assert parsed.n == 1 and seen == [1, 3, 3] and usage.tokens_in == 6


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0", 0.0), ("2.5", 2.5), ("-1", None), ("abc", None), ("", None)],
)
def test_retry_after_seconds(value: str, expected: float | None) -> None:
    response = httpx.Response(429, headers={"Retry-After": value})
    assert retry_after_seconds(response) == expected


def test_retry_after_missing_header() -> None:
    assert retry_after_seconds(httpx.Response(429)) is None


def test_post_json_returns_non_retryable_status_to_caller() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text="teapot")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = post_json(
        client, "http://x/y", {}, label="L", max_retries=2, backoff_s=0.0, max_wait_s=1.0
    )
    assert response.status_code == 418


def test_post_json_connect_errors_exhaust_retries() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("no", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match=r"L failed after 3 attempts \(ConnectError\)"):
        post_json(client, "http://x/y", {}, label="L", max_retries=2, backoff_s=0.0, max_wait_s=1.0)
    assert len(calls) == 3


def test_post_json_non_retried_transport_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="ReadTimeout"):
        post_json(client, "http://x/y", {}, label="L", max_retries=2, backoff_s=0.0, max_wait_s=1.0)
