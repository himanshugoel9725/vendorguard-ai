"""OpenAI-compatible provider (OpenAI, Groq, ...) against a mocked server: no real network."""

import json
import logging
from collections.abc import Callable
from typing import Literal

import httpx
import pytest
import respx
from pydantic import BaseModel

from vendorguard.config import Settings
from vendorguard.errors import ConfigError, LLMError, SchemaValidationError
from vendorguard.models.llm import ChatMessage
from vendorguard.providers.llm.openai_compat import OpenAICompatLLM

KEY = "sk-test-0123456789abcdef"  # fake test value  # gitleaks:allow
URL = "https://api.openai.com/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MESSAGES = [
    ChatMessage(role="system", content="Be careful."),
    ChatMessage(role="user", content="Control IAM-02 <document>SECRET-DOC</document>"),
]


class Out(BaseModel):
    status: Literal["met", "not_met"]
    note: str


GOOD = json.dumps({"status": "met", "note": "ok"})
BAD = json.dumps({"status": "maybe"})


def _reply(
    content: str | None = GOOD, prompt: int = 12, answer: int = 4, **message: object
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content, **message}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": answer},
        },
    )


@pytest.fixture
def make(settings_override: Callable[..., Settings]) -> Callable[..., OpenAICompatLLM]:
    def build(name: str = "openai", profile: dict | None = None, **llm: object) -> OpenAICompatLLM:  # type: ignore[type-arg]
        overrides = {"retry_backoff_s": 0.0, "max_retry_wait_s": 5.0, **llm}
        overrides[name] = {"api_key": KEY, **(profile or {})}
        settings = settings_override(llm=overrides).llm
        return OpenAICompatLLM(name, settings, getattr(settings, name))

    return build


def _body(route: respx.Route, index: int = 0) -> dict:  # type: ignore[type-arg]
    return json.loads(route.calls[index].request.content)


@respx.mock
def test_success_returns_output_usage_and_names(make: Callable[..., OpenAICompatLLM]) -> None:
    respx.post(URL).mock(return_value=_reply())
    llm = make()
    result = llm.complete_json(MESSAGES, Out, purpose="mapper")
    assert result.parsed == Out(status="met", note="ok")
    assert (result.usage.tokens_in, result.usage.tokens_out) == (12, 4)
    assert (result.provider, result.model, result.cached) == ("openai", llm.model, False)


@respx.mock
def test_request_has_bearer_key_schema_and_sampling_parameters(
    make: Callable[..., OpenAICompatLLM], settings_override: Callable[..., Settings]
) -> None:
    route = respx.post(URL).mock(return_value=_reply())
    make().complete_json(MESSAGES, Out, purpose="mapper", hints={"ignored": 1})
    request = route.calls[0].request
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body, s = _body(route), settings_override().llm
    assert body["model"] == s.openai.model
    assert body["messages"] == [m.model_dump() for m in MESSAGES]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Out", "schema": Out.model_json_schema()},
    }
    assert (body["temperature"], body["top_p"], body["seed"]) == (s.temperature, s.top_p, s.seed)
    assert body["max_completion_tokens"] == s.max_output_tokens and "max_tokens" not in body
    assert KEY not in request.content.decode()  # the key travels only in the header


@respx.mock
def test_the_token_limit_field_name_comes_from_the_profile(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(return_value=_reply())
    make(profile={"max_tokens_field": "max_tokens"}).complete_json(MESSAGES, Out, purpose="x")
    body = _body(route)
    assert "max_tokens" in body and "max_completion_tokens" not in body


@respx.mock
def test_parameters_a_model_rejects_can_be_omitted(make: Callable[..., OpenAICompatLLM]) -> None:
    route = respx.post(URL).mock(return_value=_reply())
    make(profile={"omit_params": ["temperature", "top_p", "seed"]}).complete_json(
        MESSAGES, Out, purpose="x"
    )
    assert not {"temperature", "top_p", "seed"} & set(_body(route))


@respx.mock
def test_json_object_mode_puts_the_schema_in_a_leading_system_message(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(return_value=_reply())
    make(profile={"response_format": "json_object"}).complete_json(MESSAGES, Out, purpose="x")
    body = _body(route)
    assert body["response_format"] == {"type": "json_object"}
    first = body["messages"][0]
    assert (
        first["role"] == "system"
        and "JSON schema" in first["content"]
        and '"status"' in first["content"]
    )
    assert body["messages"][1:] == [m.model_dump() for m in MESSAGES]


@respx.mock
def test_groq_profile_uses_its_own_endpoint_name_and_key(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(GROQ_URL).mock(return_value=_reply())
    llm = make("groq")
    result = llm.complete_json(MESSAGES, Out, purpose="x")
    assert result.provider == "groq" and result.model == "openai/gpt-oss-20b"
    assert route.calls[0].request.headers["authorization"] == f"Bearer {KEY}"


def test_a_missing_key_is_a_config_error_naming_the_variable(
    settings_override: Callable[..., Settings],
) -> None:
    s = settings_override().llm
    for name in ("openai", "groq", "openai_compat"):
        with pytest.raises(ConfigError, match=rf"VG_LLM__{name.upper()}__API_KEY"):
            OpenAICompatLLM(name, s, getattr(s, name))


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_gives_a_message_without_the_server_text(
    make: Callable[..., OpenAICompatLLM], status: int
) -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            status, json={"error": {"message": f"Incorrect API key: {KEY}"}}
        )
    )
    with pytest.raises(
        LLMError, match=rf"rejected the API key \(HTTP {status}\).*VG_LLM__OPENAI__API_KEY"
    ) as info:
        make(max_retries=3).complete_json(MESSAGES, Out, purpose="x")
    assert KEY not in str(info.value) and "Incorrect" not in str(info.value)
    assert respx.calls.call_count == 1  # never retried


@respx.mock
def test_other_client_errors_carry_the_server_message_with_the_key_redacted(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(400, json={"error": {"message": f"bad param for {KEY}"}})
    )
    with pytest.raises(LLMError, match=r"HTTP 400: bad param for \*\*\*") as info:
        make().complete_json(MESSAGES, Out, purpose="x")
    assert KEY not in str(info.value)


@respx.mock
def test_a_429_is_retried_after_the_server_asked_delay(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429, headers={"retry-after": "0.01"}, json={}), _reply()]
    )
    assert make(max_retries=2).complete_json(MESSAGES, Out, purpose="x").parsed.status == "met"
    assert route.call_count == 2


@respx.mock
def test_a_429_asking_for_too_long_a_pause_fails_at_once(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(429, headers={"retry-after": "3600"}))
    with pytest.raises(LLMError, match=r"rate limited \(HTTP 429\).*3600s.*llm\.max_retry_wait_s"):
        make(max_retries=5, max_retry_wait_s=30.0).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 1


@respx.mock
def test_a_429_that_never_clears_gives_up_after_max_retries(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(429))
    with pytest.raises(LLMError, match=r"openai failed after 3 attempts \(HTTP 429\)"):
        make(max_retries=2).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 3


@respx.mock
def test_server_errors_and_connection_errors_are_retried(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(503), httpx.ConnectError("x"), _reply()]
    )
    assert make(max_retries=2).complete_json(MESSAGES, Out, purpose="x").parsed.status == "met"
    assert route.call_count == 3


@respx.mock
def test_a_read_timeout_is_not_retried(make: Callable[..., OpenAICompatLLM]) -> None:
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(LLMError, match="ReadTimeout"):
        make(max_retries=3).complete_json(MESSAGES, Out, purpose="x")
    assert route.call_count == 1


@respx.mock
def test_an_invalid_reply_is_re_asked_and_tokens_add_up(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(side_effect=[_reply(BAD, 10, 3), _reply(GOOD, 20, 4)])
    result = make(json_repair_attempts=1).complete_json(MESSAGES, Out, purpose="x")
    assert result.parsed.status == "met" and (result.usage.tokens_in, result.usage.tokens_out) == (
        30,
        7,
    )
    assert len(_body(route, 1)["messages"]) == len(MESSAGES) + 2


@respx.mock
def test_repair_gives_up_with_a_schema_validation_error(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    respx.post(URL).mock(return_value=_reply(BAD))
    with pytest.raises(SchemaValidationError, match="after 2 attempt"):
        make(json_repair_attempts=1).complete_json(MESSAGES, Out, purpose="x")


@respx.mock
def test_a_code_fenced_reply_is_accepted(make: Callable[..., OpenAICompatLLM]) -> None:
    respx.post(URL).mock(return_value=_reply(f"```json\n{GOOD}\n```"))
    assert make().complete_json(MESSAGES, Out, purpose="x").parsed.note == "ok"


@respx.mock
@pytest.mark.parametrize(
    ("response", "needle"),
    [
        (httpx.Response(200, text="<html>"), "no message"),
        (httpx.Response(200, json={"choices": []}), "no message"),
        (httpx.Response(200, json={"choices": [{}]}), "no message"),
        (httpx.Response(200, json=["x"]), "no message"),
        (_reply(None), "empty reply"),
        (_reply("   "), "empty reply"),
        (_reply(None, refusal="I cannot help"), "refused"),
    ],
)
def test_unusable_replies_are_llm_errors(
    make: Callable[..., OpenAICompatLLM], response: httpx.Response, needle: str
) -> None:
    respx.post(URL).mock(return_value=response)
    with pytest.raises(LLMError, match=needle):
        make().complete_json(MESSAGES, Out, purpose="x")


@respx.mock
@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": -3, "completion_tokens": True}, "x"])
def test_missing_or_odd_usage_becomes_zero_tokens(
    make: Callable[..., OpenAICompatLLM], usage: object
) -> None:
    body: dict[str, object] = {"choices": [{"message": {"content": GOOD}}]}
    if usage is not None:
        body["usage"] = usage
    respx.post(URL).mock(return_value=httpx.Response(200, json=body))
    result = make().complete_json(MESSAGES, Out, purpose="x")
    assert (result.usage.tokens_in, result.usage.tokens_out) == (0, 0)


@respx.mock
def test_neither_errors_nor_logs_contain_the_key_or_the_prompt(
    make: Callable[..., OpenAICompatLLM], caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with caplog.at_level(logging.DEBUG), pytest.raises(LLMError) as info:
        make(max_retries=1).complete_json(MESSAGES, Out, purpose="x")
    for text in (str(info.value), caplog.text):
        assert KEY not in text and "SECRET-DOC" not in text


@respx.mock
def test_trailing_slash_in_base_url_and_close(make: Callable[..., OpenAICompatLLM]) -> None:
    route = respx.post(URL).mock(return_value=_reply())
    llm = make(profile={"base_url": "https://api.openai.com/v1/"})
    llm.complete_json(MESSAGES, Out, purpose="x")
    assert route.called
    llm.close()
