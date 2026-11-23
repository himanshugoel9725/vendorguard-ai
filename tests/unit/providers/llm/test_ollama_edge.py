"""Ollama provider edge cases: non-JSON errors, unicode, big replies, retry-wait rules."""

import json
import threading
from collections.abc import Callable
from typing import Literal

import httpx
import pytest
import respx
from pydantic import BaseModel

from vendorguard.config import Settings
from vendorguard.errors import LLMError, SchemaValidationError
from vendorguard.models.llm import ChatMessage
from vendorguard.providers.llm._http import MAX_ERROR_CHARS
from vendorguard.providers.llm.ollama import OllamaLLM

URL = "http://localhost:11434/api/chat"
MESSAGES = [ChatMessage(role="user", content="Prüfe Kontrolle IAM-02 ☃ 日本語")]


class Out(BaseModel):
    status: Literal["met", "not_met"]
    note: str


def _ok(content: str, **extra: object) -> httpx.Response:
    return httpx.Response(200, json={"message": {"content": content}, **extra})


@pytest.fixture
def make(settings_override: Callable[..., Settings]) -> Callable[..., OllamaLLM]:
    def build(**llm: object) -> OllamaLLM:
        return OllamaLLM(
            settings_override(llm={"provider": "ollama", "retry_backoff_s": 0.0, **llm}).llm
        )

    return build


@respx.mock
def test_non_json_error_body_is_truncated(make: Callable[..., OllamaLLM]) -> None:
    respx.post(URL).mock(return_value=httpx.Response(400, text="<html>" + "x" * 5000))
    with pytest.raises(LLMError, match="HTTP 400") as info:
        make().complete_json(MESSAGES, Out, purpose="p")
    assert len(str(info.value)) < MAX_ERROR_CHARS + 100


@respx.mock
def test_json_error_body_is_truncated(make: Callable[..., OllamaLLM]) -> None:
    respx.post(URL).mock(return_value=httpx.Response(404, json={"error": "e" * 5000}))
    with pytest.raises(LLMError) as info:
        make().complete_json(MESSAGES, Out, purpose="p")
    assert str(info.value).count("e") <= MAX_ERROR_CHARS + 20


@respx.mock
def test_unicode_round_trip_and_extra_fields_ignored(make: Callable[..., OllamaLLM]) -> None:
    reply = json.dumps({"status": "met", "note": "Größe ☃ 日本語"}, ensure_ascii=False)
    route = respx.post(URL).mock(return_value=_ok(reply, done=True, total_duration=5))
    result = make().complete_json(MESSAGES, Out, purpose="p")
    assert result.parsed.note == "Größe ☃ 日本語"
    sent = json.loads(route.calls[0].request.content)
    assert sent["messages"][0]["content"] == MESSAGES[0].content


@respx.mock
def test_very_large_reply(make: Callable[..., OllamaLLM]) -> None:
    note = "n" * 500_000
    respx.post(URL).mock(return_value=_ok(json.dumps({"status": "met", "note": note})))
    assert make().complete_json(MESSAGES, Out, purpose="p").parsed.note == note


@respx.mock
def test_usage_floats_strings_and_negative_count_as_zero(make: Callable[..., OllamaLLM]) -> None:
    respx.post(URL).mock(
        return_value=_ok(
            json.dumps({"status": "met", "note": "x"}), prompt_eval_count=1.5, eval_count="7"
        )
    )
    usage = make().complete_json(MESSAGES, Out, purpose="p").usage
    assert (usage.tokens_in, usage.tokens_out) == (0, 0)


@respx.mock
def test_repair_loop_sums_tokens_over_several_attempts(make: Callable[..., OllamaLLM]) -> None:
    bad = _ok("nope", prompt_eval_count=10, eval_count=2)
    good = _ok(json.dumps({"status": "met", "note": "x"}), prompt_eval_count=10, eval_count=2)
    route = respx.post(URL).mock(side_effect=[bad, bad, good])
    result = make(json_repair_attempts=2).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 3
    assert (result.usage.tokens_in, result.usage.tokens_out) == (30, 6)


@respx.mock
def test_repair_exhausted_raises_schema_error(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(return_value=_ok("not json"))
    with pytest.raises(SchemaValidationError, match="3 attempt"):
        make(json_repair_attempts=2).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 3


@respx.mock
@pytest.mark.parametrize("header", ["Wed, 21 Oct 2099 07:28:00 GMT", "-5", "soon"])
def test_unusable_retry_after_falls_back_to_backoff(
    make: Callable[..., OllamaLLM], header: str
) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": header}),
            _ok(json.dumps({"status": "met", "note": "x"})),
        ]
    )
    make(max_retries=1).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 2


@respx.mock
def test_retry_after_equal_to_cap_is_waited(make: Callable[..., OllamaLLM]) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "0"}),
            _ok(json.dumps({"status": "met", "note": "x"})),
        ]
    )
    make(max_retries=1, max_retry_wait_s=0.0).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 2


@respx.mock
def test_positive_retry_after_with_zero_cap_fails_at_once(
    make: Callable[..., OllamaLLM],
) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(503, headers={"Retry-After": "1"}))
    with pytest.raises(LLMError, match="rate limited"):
        make(max_retries=3, max_retry_wait_s=0.0).complete_json(MESSAGES, Out, purpose="p")
    assert route.call_count == 1


@respx.mock
def test_shared_client_used_from_threads(make: Callable[..., OllamaLLM]) -> None:
    respx.post(URL).mock(return_value=_ok(json.dumps({"status": "met", "note": "x"})))
    llm = make()
    results: list[str] = []
    errors: list[BaseException] = []

    def work() -> None:
        try:
            results.append(llm.complete_json(MESSAGES, Out, purpose="p").parsed.status)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and results == ["met"] * 8
