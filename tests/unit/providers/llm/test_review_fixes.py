"""Phase 4 review fixes: paid-but-failed calls are charged, truncation, https, backoff."""

import json
from collections.abc import Callable
from typing import Literal

import httpx
import pytest
import respx
from pydantic import BaseModel

from vendorguard.config import Settings
from vendorguard.errors import (
    BudgetExceededError,
    ConfigError,
    LLMError,
    SchemaValidationError,
    VendorGuardError,
)
from vendorguard.models.llm import ChatMessage, Usage
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.llm._http import post_json
from vendorguard.providers.llm._json import with_paid_usage
from vendorguard.providers.llm.budgeted import BudgetedLLM
from vendorguard.providers.llm.ollama import OllamaLLM
from vendorguard.providers.llm.openai_compat import OpenAICompatLLM

KEY = "sk-test-0123456789abcdef"  # fake test value  # gitleaks:allow
MSGS = [ChatMessage(role="user", content="q")]
OLLAMA = "http://localhost:11434/api/chat"
OPENAI = "https://api.openai.com/v1/chat/completions"


class Out(BaseModel):
    status: Literal["met", "not_met"]


def _ollama(content: str, prompt: int = 10, answer: int = 3, **extra: object) -> httpx.Response:
    body = {"message": {"content": content}, "prompt_eval_count": prompt, "eval_count": answer}
    return httpx.Response(200, json={**body, **extra})


def _openai(
    content: str | None, finish: str = "stop", prompt: int = 10, answer: int = 3
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": answer},
        },
    )


@pytest.fixture
def llm_settings(settings_override: Callable[..., Settings]) -> Callable[..., Settings]:
    def build(**llm: object) -> Settings:
        return settings_override(llm={"retry_backoff_s": 0.0, "openai": {"api_key": KEY}, **llm})

    return build


def _budgeted(client: object, settings: Settings) -> tuple[BudgetedLLM, CostTracker]:
    tracker = CostTracker(settings.cost)
    return BudgetedLLM(client, tracker), tracker  # type: ignore[arg-type]


# --- paid attempts that end in failure are still charged ---------------------------------------


@respx.mock
def test_exhausted_repairs_carry_the_tokens_of_every_paid_attempt(
    llm_settings: Callable[..., Settings],
) -> None:
    respx.post(OLLAMA).mock(side_effect=[_ollama("{}", 10, 3), _ollama("{}", 20, 4)])
    client = OllamaLLM(llm_settings(json_repair_attempts=1).llm)
    with pytest.raises(SchemaValidationError) as info:
        client.complete_json(MSGS, Out, purpose="x")
    assert info.value.paid_usage == (30, 7)


@respx.mock
def test_a_failure_after_a_paid_repair_carries_the_earlier_tokens(
    llm_settings: Callable[..., Settings],
) -> None:
    respx.post(OLLAMA).mock(
        side_effect=[_ollama("{}", 10, 3), httpx.Response(400, json={"error": "bad"})]
    )
    client = OllamaLLM(llm_settings(json_repair_attempts=1).llm)
    with pytest.raises(LLMError) as info:
        client.complete_json(MSGS, Out, purpose="x")
    assert info.value.paid_usage == (10, 3)


@respx.mock
def test_the_budget_guard_charges_a_call_that_failed_after_paying(
    llm_settings: Callable[..., Settings],
) -> None:
    respx.post(OLLAMA).mock(return_value=_ollama("{}", 10, 3))
    s = llm_settings(json_repair_attempts=1)
    guarded, tracker = _budgeted(OllamaLLM(s.llm), s)
    with pytest.raises(SchemaValidationError):
        guarded.complete_json(MSGS, Out, purpose="x")
    summary = tracker.summary()
    assert (summary.llm_calls, summary.tokens_in, summary.tokens_out) == (1, 20, 6)


def test_a_failure_without_paid_tokens_charges_nothing(
    llm_settings: Callable[..., Settings],
) -> None:
    class Failing:
        provider, model = "ollama", "m"

        def complete_json(self, *a: object, **k: object) -> None:
            raise LLMError("connection refused")

    s = llm_settings()
    guarded, tracker = _budgeted(Failing(), s)
    with pytest.raises(LLMError, match="refused"):
        guarded.complete_json(MSGS, Out, purpose="x")
    assert tracker.summary().llm_calls == 0


def test_paid_usage_defaults_to_none_and_helper_ignores_zero_usage() -> None:
    for error in (VendorGuardError(), ConfigError("x"), LLMError("x"), BudgetExceededError("x")):
        assert error.paid_usage is None
    assert with_paid_usage(LLMError("x"), Usage()).paid_usage is None
    assert with_paid_usage(LLMError("x"), Usage(tokens_in=1)).paid_usage == (1, 0)


# --- truncated replies -------------------------------------------------------------------------


@respx.mock
def test_a_reply_cut_off_by_the_token_limit_is_a_clear_error_and_not_re_asked(
    llm_settings: Callable[..., Settings],
) -> None:
    route = respx.post(OPENAI).mock(return_value=_openai('{"status": "me', "length", 12, 800))
    s = llm_settings(json_repair_attempts=3)
    client = OpenAICompatLLM("openai", s.llm, s.llm.openai)
    with pytest.raises(
        LLMError, match=r"cut off at llm\.max_output_tokens \(800\).*reasoning"
    ) as info:
        client.complete_json(MSGS, Out, purpose="x")
    assert route.call_count == 1 and info.value.paid_usage == (12, 800)


@respx.mock
def test_ollama_reports_a_truncated_reply_too(llm_settings: Callable[..., Settings]) -> None:
    route = respx.post(OLLAMA).mock(return_value=_ollama('{"status"', 9, 800, done_reason="length"))
    client = OllamaLLM(llm_settings(json_repair_attempts=3).llm)
    with pytest.raises(LLMError, match="cut off at llm.max_output_tokens") as info:
        client.complete_json(MSGS, Out, purpose="x")
    assert route.call_count == 1 and info.value.paid_usage == (9, 800)


@respx.mock
def test_a_normal_stop_and_an_empty_reply_still_work_as_before(
    llm_settings: Callable[..., Settings],
) -> None:
    s = llm_settings()
    client = OpenAICompatLLM("openai", s.llm, s.llm.openai)
    respx.post(OPENAI).mock(return_value=_openai(json.dumps({"status": "met"}), "stop"))
    assert client.complete_json(MSGS, Out, purpose="x").parsed.status == "met"
    respx.post(OPENAI).mock(return_value=_openai("", "stop", 7, 0))
    with pytest.raises(LLMError, match="empty reply") as info:
        client.complete_json(MSGS, Out, purpose="x")
    assert info.value.paid_usage == (7, 0)


# --- keys only travel over https ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://api.openai.com/v1", True),
        ("http://localhost:8080/v1", True),
        ("http://127.0.0.1:9000", True),
        ("http://[::1]:9000/v1", True),
        ("http://api.openai.com/v1", False),
        ("http://192.168.1.5:8000/v1", False),
        ("http://localhost.evil.example/v1", False),
        ("ftp://example.com", False),
    ],
)
def test_a_bearer_key_is_only_sent_over_https_or_to_loopback(
    llm_settings: Callable[..., Settings], url: str, ok: bool
) -> None:
    s = llm_settings(openai={"api_key": KEY, "base_url": url})
    if ok:
        OpenAICompatLLM("openai", s.llm, s.llm.openai)
    else:
        with pytest.raises(ConfigError, match=r"llm\.openai\.base_url must use https"):
            OpenAICompatLLM("openai", s.llm, s.llm.openai)


# --- exponential backoff -----------------------------------------------------------------------


@respx.mock
def test_the_pause_doubles_each_attempt_and_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr("tenacity.nap.time.sleep", waits.append)
    respx.post("http://host/x").mock(side_effect=[httpx.Response(503)] * 4 + [httpx.Response(200)])
    post_json(
        httpx.Client(), "http://host/x", {}, label="T", max_retries=4, backoff_s=1.0, max_wait_s=5.0
    )
    assert waits == [1.0, 2.0, 4.0, 5.0]  # doubled, then capped at max_wait_s


@respx.mock
def test_zero_backoff_never_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr("tenacity.nap.time.sleep", waits.append)
    respx.post("http://host/x").mock(side_effect=[httpx.Response(503), httpx.Response(200)])
    post_json(
        httpx.Client(), "http://host/x", {}, label="T", max_retries=2, backoff_s=0.0, max_wait_s=5.0
    )
    assert waits == [0.0]
