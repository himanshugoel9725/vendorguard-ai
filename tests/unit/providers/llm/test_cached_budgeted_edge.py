"""CachedLLM and BudgetedLLM edge cases: threads, odd hints, failing caches, exact limits."""

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest
from pydantic import BaseModel

from vendorguard.config import Settings
from vendorguard.errors import BudgetExceededError, CacheMissError, LLMError
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.llm.budgeted import BudgetedLLM
from vendorguard.providers.llm.cached import CachedLLM

MSGS = [ChatMessage(role="user", content="q")]


class Out(BaseModel):
    answer: str


class Other(BaseModel):
    count: int = 0


class Hint(BaseModel):
    name: str


class Inner:
    def __init__(self, provider: str = "openai", model: str = "gpt-6-luna", tokens: int = 10):
        self.provider, self.model, self.tokens, self.calls = provider, model, tokens, 0
        self.fail = False

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
        return (
            LLMResult(
                parsed=output_model(),
                usage=Usage(tokens_in=self.tokens, tokens_out=self.tokens),
                provider=self.provider,
                model=self.model,
            )
            if output_model is Other
            else LLMResult(
                parsed=output_model(answer="a"),
                usage=Usage(tokens_in=self.tokens, tokens_out=self.tokens),
                provider=self.provider,
                model=self.model,
            )
        )


class DictCache:
    def __init__(self, fail_put: bool = False) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self.puts = 0
        self.fail_put = fail_put
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        with self._lock:
            self.puts += 1
        if self.fail_put:
            raise OSError("disk full")
        self.data[key] = value


def _ask(llm: CachedLLM | BudgetedLLM, model: type[Any] = Out, **kw: Any) -> LLMResult[Any]:
    return llm.complete_json(MSGS, model, purpose="mapper", **kw)


# --- CachedLLM -----------------------------------------------------------------------------------


def test_threads_with_the_same_key_each_call_the_client_and_write_one_entry() -> None:
    """Documents current behaviour: there is no single-flight, so racing misses all call out."""
    inner, cache = Inner(), DictCache()
    llm = CachedLLM(inner, cache, "read_write", {"seed": 1})
    barrier = threading.Barrier(6)

    def work() -> None:
        barrier.wait()
        _ask(llm)

    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert 1 <= inner.calls <= 6 and len(cache.data) == 1
    assert llm.hits + llm.misses == 6 and _ask(llm).cached


def test_nested_hints_are_hashed_and_distinguish_entries() -> None:
    inner, cache = Inner(), DictCache()
    llm = CachedLLM(inner, cache, "read_write", {"seed": 1})
    hints = {"a": {"b": [1, {"c": [2, 3]}]}, "z": [[1], [2]]}
    _ask(llm, hints=hints)
    assert _ask(llm, hints={"z": [[1], [2]], "a": {"b": [1, {"c": [2, 3]}]}}).cached  # key order
    assert not _ask(llm, hints={"a": {"b": [1, {"c": [2, 4]}]}, "z": [[1], [2]]}).cached
    assert inner.calls == 2


def test_hints_with_pydantic_models_work_or_fail_clearly() -> None:
    llm = CachedLLM(Inner(), DictCache(), "read_write", {"seed": 1})
    try:
        _ask(llm, hints={"h": Hint(name="x")})
    except TypeError:
        return  # documented alternative: unsupported hint types are rejected, never mis-keyed
    assert _ask(llm, hints={"h": Hint(name="x")}).cached
    assert not _ask(llm, hints={"h": Hint(name="y")}).cached


def test_a_failing_put_propagates_from_complete_json_after_the_client_call() -> None:
    """Documents current behaviour: cache write errors are not swallowed."""
    inner, cache = Inner(), DictCache(fail_put=True)
    llm = CachedLLM(inner, cache, "read_write", {"seed": 1})
    with pytest.raises(OSError, match="disk full"):
        _ask(llm)
    assert inner.calls == 1 and cache.puts == 1 and llm.misses == 1


def test_read_only_entry_for_another_output_model_is_a_miss() -> None:
    inner, cache = Inner(), DictCache()
    writer = CachedLLM(inner, cache, "read_write", {"seed": 1})
    _ask(writer)  # recorded as Out; the key includes the schema, so Other is a different key
    reader = CachedLLM(inner, cache, "read_only", {"seed": 1})
    with pytest.raises(CacheMissError):
        _ask(reader, Other)
    assert inner.calls == 1 and reader.misses == 1 and reader.hits == 0


def test_read_only_entry_with_wrong_shape_under_the_same_key_is_a_miss() -> None:
    inner, cache = Inner(), DictCache()
    _ask(CachedLLM(inner, cache, "read_write", {"seed": 1}))
    for entry in cache.data.values():
        entry["parsed"] = {"unexpected": True}
    with pytest.raises(CacheMissError):
        _ask(CachedLLM(inner, cache, "read_only", {"seed": 1}))


def test_cache_none_forces_off_mode() -> None:
    inner = Inner()
    llm = CachedLLM(inner, None, "read_only", {"seed": 1})
    _ask(llm)
    _ask(llm)
    assert inner.calls == 2 and (llm.hits, llm.misses) == (0, 0)


def test_on_hit_callback_called_per_replay() -> None:
    hits: list[int] = []
    llm = CachedLLM(Inner(), DictCache(), "read_write", {"seed": 1}, on_hit=lambda: hits.append(1))
    for _ in range(4):
        _ask(llm)
    assert len(hits) == 3


def test_unicode_and_large_messages_round_trip() -> None:
    inner, cache = Inner(), DictCache()
    llm = CachedLLM(inner, cache, "read_write", {"seed": 1})
    big = [ChatMessage(role="user", content="日本語☃" * 200_000)]
    llm.complete_json(big, Out, purpose="p")
    assert llm.complete_json(big, Out, purpose="p").cached and inner.calls == 1


# --- BudgetedLLM ---------------------------------------------------------------------------------


@pytest.fixture
def tracker(settings_override: Callable[..., Settings]) -> Callable[..., CostTracker]:
    def build(**cost: object) -> CostTracker:
        return CostTracker(settings_override(cost=cost).cost)

    return build


def test_provider_and_model_propagate_to_results(tracker: Callable[..., CostTracker]) -> None:
    llm = BudgetedLLM(Inner("ollama", "llama-x"), tracker())
    result = _ask(llm)
    assert (llm.provider, llm.model) == ("ollama", "llama-x")
    assert (result.provider, result.model) == ("ollama", "llama-x")


def test_client_exception_leaves_tracker_untouched(tracker: Callable[..., CostTracker]) -> None:
    t, inner = tracker(), Inner()
    inner.fail = True
    llm = BudgetedLLM(inner, t)
    for _ in range(3):
        with pytest.raises(LLMError):
            _ask(llm)
    s = t.summary()
    assert (s.llm_calls, s.tokens_in, s.tokens_out, s.usd, s.cache_hits) == (0, 0, 0, 0.0, 0)


def test_exactly_at_the_call_limit_allows_the_last_call_and_blocks_the_next(
    tracker: Callable[..., CostTracker],
) -> None:
    inner = Inner()
    llm = BudgetedLLM(inner, tracker(max_llm_calls_per_run=2, max_usd_per_run=100.0))
    _ask(llm)
    _ask(llm)  # the 2nd call is exactly at the limit and must succeed
    with pytest.raises(BudgetExceededError):
        _ask(llm)
    assert inner.calls == 2


def test_zero_cost_mock_never_counts_against_the_dollar_budget(
    tracker: Callable[..., CostTracker],
) -> None:
    llm = BudgetedLLM(Inner("mock", "keyword-baseline", tokens=0), tracker(max_llm_calls_per_run=5))
    for _ in range(5):
        _ask(llm)
    assert llm.provider == "mock"
