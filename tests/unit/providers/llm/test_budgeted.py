"""BudgetedLLM: the guard around a client, including replays from the cache."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest
from pydantic import BaseModel

from vendorguard.config import Settings
from vendorguard.errors import BudgetExceededError, ConfigError, LLMError
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.llm.budgeted import BudgetedLLM
from vendorguard.providers.llm.cached import CachedLLM

MSGS = [ChatMessage(role="user", content="q")]


class Out(BaseModel):
    answer: str


class Inner:
    def __init__(
        self, provider: str = "openai", model: str = "gpt-6-luna", tokens: int = 100
    ) -> None:
        self.provider, self.model, self.tokens, self.calls, self.fail = (
            provider,
            model,
            tokens,
            0,
            False,
        )

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[Any],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[Any]:
        self.calls += 1
        if self.fail:
            raise LLMError("boom")
        return LLMResult(
            parsed=output_model(answer="a"),
            usage=Usage(tokens_in=self.tokens, tokens_out=self.tokens),
            provider=self.provider,
            model=self.model,
        )


class DictCache:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        self.data[key] = value


@pytest.fixture
def tracker(settings_override: Callable[..., Settings]) -> Callable[..., CostTracker]:
    def build(**cost: object) -> CostTracker:
        return CostTracker(settings_override(cost=cost).cost)

    return build


def _ask(llm: BudgetedLLM, text: str = "q") -> LLMResult[Out]:
    return llm.complete_json([ChatMessage(role="user", content=text)], Out, purpose="mapper")


def test_the_call_budget_stops_the_run_and_the_extra_call_is_never_made(
    tracker: Callable[..., CostTracker],
) -> None:
    """Task 4.6 done-when: a budget test stops the run."""
    inner = Inner()
    llm = BudgetedLLM(inner, tracker(max_llm_calls_per_run=3, max_usd_per_run=100.0))
    for n in range(3):
        _ask(llm, f"q{n}")
    with pytest.raises(BudgetExceededError, match="max_llm_calls_per_run"):
        _ask(llm, "q3")
    assert inner.calls == 3


def test_the_dollar_budget_stops_the_run_after_the_call_that_crossed_it(
    tracker: Callable[..., CostTracker],
) -> None:
    inner = Inner(tokens=2_000_000)  # 2M in + 2M out at 0.10 / 0.50 = $1.20
    llm = BudgetedLLM(inner, tracker(max_usd_per_run=0.50))
    with pytest.raises(BudgetExceededError, match="above cost.max_usd_per_run"):
        _ask(llm)
    with pytest.raises(BudgetExceededError, match="reached cost.max_usd_per_run"):
        _ask(llm, "again")
    assert inner.calls == 1


def test_an_unpriced_model_is_refused_before_the_call(tracker: Callable[..., CostTracker]) -> None:
    inner = Inner("openai", "model-without-a-price")
    llm = BudgetedLLM(inner, tracker())
    # openai/* is not in the committed table, only the exact default model is
    with pytest.raises(ConfigError, match="no price"):
        _ask(llm)
    assert inner.calls == 0


def test_costs_are_recorded_for_each_call(tracker: Callable[..., CostTracker]) -> None:
    t = tracker(max_usd_per_run=100.0)
    llm = BudgetedLLM(Inner(tokens=1_000_000), t)
    _ask(llm)
    s = t.summary()
    assert (s.llm_calls, s.tokens_in, s.tokens_out, s.usd) == (1, 1_000_000, 1_000_000, 0.60)


def _cached(inner: Inner, t: CostTracker) -> CachedLLM:
    return CachedLLM(
        BudgetedLLM(inner, t), DictCache(), "read_write", {"seed": 1}, on_hit=t.record_cache_hit
    )


def test_replays_are_cache_hits_and_do_not_use_the_call_budget(
    tracker: Callable[..., CostTracker],
) -> None:
    inner = Inner()
    t = tracker(max_llm_calls_per_run=1, max_usd_per_run=100.0)
    llm = _cached(inner, t)
    for _ in range(5):
        _ask(llm)  # one real call, four replays
    s = t.summary()
    assert (s.llm_calls, s.cache_hits, inner.calls) == (1, 4, 1)


def test_replays_still_work_after_the_budget_is_spent_but_new_calls_do_not(
    tracker: Callable[..., CostTracker],
) -> None:
    inner = Inner()
    t = tracker(max_llm_calls_per_run=1, max_usd_per_run=100.0)
    llm = _cached(inner, t)
    _ask(llm, "recorded")
    assert _ask(llm, "recorded").cached  # budget exhausted, replay is fine
    with pytest.raises(BudgetExceededError):
        _ask(llm, "a new question")
    assert inner.calls == 1


def test_a_failing_call_records_nothing(tracker: Callable[..., CostTracker]) -> None:
    inner, t = Inner(), tracker()
    inner.fail = True
    with pytest.raises(LLMError):
        _ask(BudgetedLLM(inner, t))
    assert t.summary().llm_calls == 0


def test_provider_and_model_come_from_the_wrapped_client(
    tracker: Callable[..., CostTracker],
) -> None:
    llm = BudgetedLLM(Inner("groq", "m"), tracker())
    assert (llm.provider, llm.model) == ("groq", "m")
