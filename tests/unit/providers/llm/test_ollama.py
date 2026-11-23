"""Ollama LLM provider against a mocked server: request shape, repair, retries, errors."""

import json
from collections.abc import Callable
from typing import Literal

import httpx
import pytest
import respx
from pydantic import BaseModel

from vendorguard.config import Settings
from vendorguard.errors import LLMError, SchemaValidationError
from vendorguard.models.llm import ChatMessage
from vendorguard.providers.llm.ollama import OllamaLLM

URL = "http://localhost:11434/api/chat"
MESSAGES = [
    ChatMessage(role="system", content="You are a careful assessor."),
    ChatMessage(role="user", content="Control IAM-02. <document>SECRET-DOC text</document>"),
]


class Out(BaseModel):
    status: Literal["met", "not_met"]
    note: str


def _reply(content: str, prompt: int | None = 11, answer: int | None = 5) -> httpx.Response:
    body: dict[str, object] = {"message": {"role": "assistant", "content": content}}
    if prompt is not None:
        body["prompt_eval_count"] = prompt
    if answer is not None:
        body["eval_count"] = answer
    return httpx.Response(200, json=body)


GOOD = json.dumps({"status": "met", "note": "ok"})
BAD = json.dumps({"status": "maybe"})


@pytest.fixture
def make(settings_override: Callable[..., Settings]) -> Callable[..., OllamaLLM]:
    def build(**llm: object) -> OllamaLLM:
        settings = settings_override(llm={"provider": "ollama", "retry_backoff_s": 0.0, **llm}).llm
        return OllamaLLM(settings)

    return build


def _bodies(route: respx.Route) -> list[dict]:  # type: ignore[type-arg]
    return [json.loads(call.request.content) for call in route.calls]


@respx.mock
def test_success_returns_the_validated_output_with_usage(
    make: Callable[..., OllamaLLM], settings_override: Callable[..., Settings]
) -> None:
    respx.post(URL).mock(return_value=_reply(GOOD))
    result = make().complete_json(MESSAGES, Out, purpose="mapper")
    assert result.parsed == Out(status="met", note="ok")
    assert (result.usage.tokens_in, result.usage.tokens_out) == (11, 5)
    assert (result.provider, result.cached) == ("ollama", False)
    assert result.model == settings_override().llm.model
    assert result.latency_ms >= 0


@respx.mock
def test_request_carries_messages_schema_and_options_from_settings(
    make: Callable[..., OllamaLLM], settings_override: Callable[..., Settings]
) -> None:
    route = respx.post(URL).mock(return_value=_reply(GOOD))
    make().complete_json(MESSAGES, Out, purpose="mapper", hints={"ignored": 1})
    body = _bodies(route)[0]
    s = settings_override().llm
    assert body["model"] == s.model and body["stream"] is False
    assert body["messages"] == [m.model_dump() for m in MESSAGES]
    assert body["format"] == Out.model_json_schema()
    assert body["options"] == {
        "temperature": s.temperature,
        "seed": s.seed,
        "top_p": s.top_p,
        "num_ctx": s.context_window,
        "num_predict": s.max_output_tokens,
    }
    assert set(body) == {
        "model",
        "messages",
        "format",
        "stream",
        "options",
    }  # purpose, hints stay local


@respx.mock
def test_options_follow_changed_settings(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(return_value=_reply(GOOD))
    make(seed=7, temperature=0.0, context_window=2048, max_output_tokens=64).complete_json(
        MESSAGES, Out, purpose="x"
    )
    opts = _bodies(route)[0]["options"]
    assert (opts["seed"], opts["num_ctx"], opts["num_predict"]) == (7, 2048, 64)


@respx.mock
def test_the_same_call_sends_identical_requests(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(return_value=_reply(GOOD))
    llm = make()
    llm.complete_json(MESSAGES, Out, purpose="x")
    llm.complete_json(MESSAGES, Out, purpose="x")
    assert _bodies(route)[0] == _bodies(route)[1]


@respx.mock
def test_an_invalid_reply_is_re_asked_with_the_problem_and_tokens_add_up(
    make: Callable[..., OllamaLLM],
) -> None:
    route = respx.post(URL).mock(side_effect=[_reply(BAD, 10, 3), _reply(GOOD, 20, 4)])
    result = make(json_repair_attempts=1).complete_json(MESSAGES, Out, purpose="x")
    assert result.parsed.status == "met"
    assert (result.usage.tokens_in, result.usage.tokens_out) == (30, 7)
    first, second = _bodies(route)
    assert len(first["messages"]) == 2 and len(second["messages"]) == 4
    assert second["messages"][2] == {"role": "assistant", "content": BAD}
    follow_up = second["messages"][3]["content"]
    assert follow_up.startswith("Your previous reply was not valid") and "status" in follow_up
    assert "maybe" not in follow_up  # the offending value is not echoed


@respx.mock
def test_repair_gives_up_after_the_configured_attempts(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(return_value=_reply(BAD))
    with pytest.raises(SchemaValidationError, match=r"Out: invalid output after 3 attempt"):
        make(json_repair_attempts=2).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 3


@respx.mock
def test_no_repair_attempts_means_one_call(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(return_value=_reply("not json at all"))
    with pytest.raises(SchemaValidationError, match="after 1 attempt"):
        make(json_repair_attempts=0).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 1


@respx.mock
def test_a_markdown_code_fence_around_the_json_is_accepted(make: Callable[..., OllamaLLM]) -> None:
    respx.post(URL).mock(return_value=_reply(f"```json\n{GOOD}\n```"))
    assert make().complete_json(MESSAGES, Out, purpose="x").parsed.note == "ok"


@respx.mock
def test_a_read_timeout_is_an_llm_error_and_is_not_retried(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(LLMError, match="ReadTimeout"):
        make(max_retries=3).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 1


@respx.mock
def test_connection_errors_are_retried_until_one_succeeds(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.ConnectError("refused"), httpx.ConnectTimeout("t"), _reply(GOOD)]
    )
    assert make(max_retries=2).complete_json(MESSAGES, Out, purpose="x").parsed.status == "met"
    assert route.call_count == 3


@respx.mock
def test_connection_errors_give_up_after_max_retries(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMError, match=r"failed after 3 attempts \(ConnectError\)"):
        make(max_retries=2).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 3


@respx.mock
def test_server_errors_are_retried(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(500, text="boom"), httpx.Response(503), _reply(GOOD)]
    )
    assert make(max_retries=2).complete_json(MESSAGES, Out, purpose="x").parsed.status == "met"
    assert route.call_count == 3


@respx.mock
def test_server_errors_that_persist_become_an_llm_error(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(LLMError, match="failed after 2 attempts"):
        make(max_retries=1).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 2


@respx.mock
def test_max_retries_zero_means_a_single_attempt(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMError, match="failed after 1 attempts"):
        make(max_retries=0).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 404, 429])
def test_client_errors_are_not_retried_and_carry_the_server_message(
    make: Callable[..., OllamaLLM], status: int
) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(status, json={"error": "model not found"})
    )
    with pytest.raises(LLMError, match=rf"HTTP {status}: model not found"):
        make(max_retries=3).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>no</html>"),
        httpx.Response(200, json={"nope": 1}),
        httpx.Response(200, json={"message": {"role": "assistant"}}),
        httpx.Response(200, json={"message": {"content": 5}}),
        httpx.Response(200, json=["list"]),
    ],
)
def test_unusable_success_bodies_are_llm_errors(
    make: Callable[..., OllamaLLM], response: httpx.Response
) -> None:
    respx.post(URL).mock(return_value=response)
    with pytest.raises(LLMError, match="unusable"):
        make().complete_json(MESSAGES, Out, purpose="x")


@respx.mock
@pytest.mark.parametrize(("prompt", "answer"), [(None, None), (-4, True), ("9", 2.5)])
def test_missing_or_odd_token_counts_become_zero(
    make: Callable[..., OllamaLLM], prompt: object, answer: object
) -> None:
    body: dict[str, object] = {"message": {"content": GOOD}}
    if prompt is not None:
        body["prompt_eval_count"] = prompt
    if answer is not None:
        body["eval_count"] = answer
    respx.post(URL).mock(return_value=httpx.Response(200, json=body))
    usage = make().complete_json(MESSAGES, Out, purpose="x").usage
    assert (usage.tokens_in, usage.tokens_out) == (0, 0)


@respx.mock
def test_errors_never_contain_the_prompt_text(make: Callable[..., OllamaLLM]) -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMError) as info:
        make(max_retries=0).complete_json(MESSAGES, Out, purpose="x")
    assert "SECRET-DOC" not in str(info.value)
    respx.post(URL).mock(return_value=_reply("garbage"))
    with pytest.raises(SchemaValidationError) as info2:
        make(json_repair_attempts=0).complete_json(MESSAGES, Out, purpose="x")
    assert "SECRET-DOC" not in str(info2.value)


@respx.mock
def test_trailing_slash_in_base_url_and_close(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(return_value=_reply(GOOD))
    llm = make(base_url="http://localhost:11434/")
    llm.complete_json(MESSAGES, Out, purpose="x")
    assert route.called
    llm.close()
