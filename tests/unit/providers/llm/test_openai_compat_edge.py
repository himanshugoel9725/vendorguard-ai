"""OpenAI-compatible provider edge cases: errors, redaction, body shape, retries."""

import json
import logging
import threading
from collections.abc import Callable
from typing import Literal

import httpx
import pytest
import respx
from pydantic import BaseModel

from vendorguard.config import Settings
from vendorguard.errors import LLMError
from vendorguard.models.llm import ChatMessage
from vendorguard.providers.llm._http import MAX_ERROR_CHARS
from vendorguard.providers.llm.openai_compat import OpenAICompatLLM

KEY = "sk-test-edge0123456789abcdef"  # fake test value  # gitleaks:allow
URL = "https://api.openai.com/v1/chat/completions"
MESSAGES = [ChatMessage(role="user", content="Kontrolle ☃ 日本語")]
GOOD = json.dumps({"status": "met", "note": "ok"})


class Out(BaseModel):
    status: Literal["met", "not_met"]
    note: str


def _ok(content: str = GOOD, usage: object = None, **top: object) -> httpx.Response:
    body: dict[str, object] = {"choices": [{"message": {"content": content}}], **top}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


@pytest.fixture
def make(settings_override: Callable[..., Settings]) -> Callable[..., OpenAICompatLLM]:
    def build(profile: dict | None = None, **llm: object) -> OpenAICompatLLM:  # type: ignore[type-arg]
        overrides = {"retry_backoff_s": 0.0, "max_retry_wait_s": 5.0, **llm}
        overrides["openai"] = {"api_key": KEY, **(profile or {})}
        settings = settings_override(llm=overrides).llm
        return OpenAICompatLLM("openai", settings, settings.openai)

    return build


def _body(route: respx.Route) -> dict:  # type: ignore[type-arg]
    return json.loads(route.calls[0].request.content)


@respx.mock
def test_non_json_error_body_truncated_and_key_redacted(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    text = KEY + "y" * 5000 + KEY
    respx.post(URL).mock(return_value=httpx.Response(400, text=text))
    with pytest.raises(LLMError, match="HTTP 400") as info:
        make().complete_json(MESSAGES, Out, purpose="p")
    assert KEY not in str(info.value)
    assert len(str(info.value)) < MAX_ERROR_CHARS + 100


@respx.mock
@pytest.mark.parametrize("prefix", ["", "x" * 190])
def test_key_redacted_in_every_position_of_error_message(
    make: Callable[..., OpenAICompatLLM], prefix: str
) -> None:
    message = f"{prefix}bad {KEY} end"
    respx.post(URL).mock(return_value=httpx.Response(400, json={"error": {"message": message}}))
    with pytest.raises(LLMError) as info:
        make().complete_json(MESSAGES, Out, purpose="p")
    assert KEY not in str(info.value) and KEY[:12] not in str(info.value)


@respx.mock
def test_error_as_plain_string(make: Callable[..., OpenAICompatLLM]) -> None:
    respx.post(URL).mock(return_value=httpx.Response(400, json={"error": "plain failure"}))
    with pytest.raises(LLMError, match="plain failure"):
        make().complete_json(MESSAGES, Out, purpose="p")


@respx.mock
def test_authorization_header_never_in_errors_or_logs(
    make: Callable[..., OpenAICompatLLM], caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(URL).mock(return_value=httpx.Response(503))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMError) as info:
        make(max_retries=1).complete_json(MESSAGES, Out, purpose="p")
    assert KEY not in str(info.value) and "Bearer" not in str(info.value)
    assert KEY not in caplog.text


@respx.mock
def test_429_without_header_is_retried_with_backoff(make: Callable[..., OpenAICompatLLM]) -> None:
    route = respx.post(URL).mock(side_effect=[httpx.Response(429), _ok()])
    make(max_retries=1).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 2


@respx.mock
def test_5xx_with_retry_after_within_cap_is_retried(make: Callable[..., OpenAICompatLLM]) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(502, headers={"Retry-After": "0"}), _ok()]
    )
    make(max_retries=1).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 2


@respx.mock
def test_zero_cap_with_positive_retry_after_fails_at_once(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "2"}))
    with pytest.raises(LLMError, match="rate limited"):
        make(max_retries=3, max_retry_wait_s=0.0).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("header", ["Wed, 21 Oct 2099 07:28:00 GMT", "-1"])
def test_date_or_negative_retry_after_is_ignored(
    make: Callable[..., OpenAICompatLLM], header: str
) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": header}), _ok()]
    )
    make(max_retries=1).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 2


@respx.mock
def test_omit_params_given_twice(make: Callable[..., OpenAICompatLLM]) -> None:
    route = respx.post(URL).mock(return_value=_ok())
    make(profile={"omit_params": ["seed", "seed", "top_p"]}).complete_json(
        MESSAGES, Out, purpose="p"
    )
    body = _body(route)
    assert "seed" not in body and "top_p" not in body and "temperature" in body


@respx.mock
def test_json_object_mode_prepends_schema_system_message_even_if_system_present(
    make: Callable[..., OpenAICompatLLM],
) -> None:
    route = respx.post(URL).mock(return_value=_ok())
    msgs = [ChatMessage(role="system", content="mine"), *MESSAGES]
    make(profile={"response_format": "json_object"}).complete_json(msgs, Out, purpose="p")
    sent = _body(route)["messages"]
    assert sent[0]["role"] == "system" and "JSON schema" in sent[0]["content"]
    assert sent[1]["content"] == "mine" and len(sent) == 3


@respx.mock
def test_first_choice_used_and_extra_fields_ignored(make: Callable[..., OpenAICompatLLM]) -> None:
    other = json.dumps({"status": "not_met", "note": "second"})
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": GOOD}}, {"message": {"content": other}}],
                "id": "abc",
                "system_fingerprint": "fp",
            },
        )
    )
    assert make().complete_json(MESSAGES, Out, purpose="p").parsed.status == "met"


@respx.mock
@pytest.mark.parametrize(
    "usage",
    [{"prompt_tokens": 1.5, "completion_tokens": "7"}, "not a dict", [1, 2], {"prompt_tokens": -3}],
)
def test_odd_usage_counts_as_zero(make: Callable[..., OpenAICompatLLM], usage: object) -> None:
    respx.post(URL).mock(return_value=_ok(usage=usage))
    result = make().complete_json(MESSAGES, Out, purpose="p")
    assert (result.usage.tokens_in, result.usage.tokens_out) == (0, 0)


@respx.mock
def test_unicode_and_large_reply(make: Callable[..., OpenAICompatLLM]) -> None:
    note = "日本語☃" * 100_000
    respx.post(URL).mock(return_value=_ok(json.dumps({"status": "met", "note": note})))
    result = make().complete_json(MESSAGES, Out, purpose="p")
    assert result.parsed.note == note and result.provider == "openai"


@respx.mock
def test_threads_share_one_client(make: Callable[..., OpenAICompatLLM]) -> None:
    respx.post(URL).mock(return_value=_ok())
    llm = make()
    out: list[str] = []
    threads = [
        threading.Thread(
            target=lambda: out.append(llm.complete_json(MESSAGES, Out, purpose="p").parsed.status)
        )
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert out == ["met"] * 8
