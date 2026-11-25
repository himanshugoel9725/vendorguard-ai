"""Cost tracker: price lookup, exact dollar sums, call counting and hard budgets."""

import logging
import threading
from collections.abc import Callable

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.providers import CostSettings
from vendorguard.errors import BudgetExceededError, ConfigError
from vendorguard.models.llm import Usage
from vendorguard.observability.cost_tracker import CostTracker

Make = Callable[..., CostTracker]


@pytest.fixture
def make(settings_override: Callable[..., Settings]) -> Make:
    def build(prices: dict | None = None, **cost: object) -> CostTracker:  # type: ignore[type-arg]
        overrides: dict[str, object] = dict(cost)
        settings = settings_override(cost=overrides).cost
        if prices is not None:
            settings = CostSettings.model_validate(
                {**settings.model_dump(), "prices_per_million_tokens": prices}
            )
        return CostTracker(settings)

    return build


PRICES = {
    "openai/*": {"input": 1.0, "output": 2.0},
    "openai/gpt-6-luna": {"input": 0.10, "output": 0.50},
    "groq/*": {"input": 0.0, "output": 0.0},
    "x/y/*": {"input": 3.0, "output": 4.0},
}


# --- price lookup --------------------------------------------------------------------------------


def test_the_most_specific_pattern_wins(make: Make) -> None:
    tracker = make(PRICES)
    assert tracker.price_for("openai", "gpt-6-luna").input == 0.10  # exact beats openai/*
    assert tracker.price_for("openai", "gpt-other").input == 1.0
    assert (
        tracker.price_for("groq", "openai/gpt-oss-20b").output == 0.0
    )  # model names may contain '/'
    assert tracker.price_for("x", "y/z").output == 4.0


def test_an_unpriced_model_is_a_config_error_naming_it(make: Make) -> None:
    with pytest.raises(
        ConfigError, match=r"no price for 'otherco/other-model'.*cost\.prices_per_million_tokens"
    ):
        make(PRICES).price_for("otherco", "other-model")


def test_the_committed_prices_cover_every_default_provider(
    settings_override: Callable[..., Settings],
) -> None:
    tracker = CostTracker(settings_override().cost)
    s = settings_override().llm
    assert tracker.price_for("ollama", s.model).input == 0.0
    assert tracker.price_for("mock", "keyword-baseline").output == 0.0
    assert (
        tracker.price_for("openai", s.openai.model).input,
        tracker.price_for("openai", s.openai.model).output,
    ) == (0.10, 0.50)
    assert tracker.price_for("groq", s.groq.model).input == 0.0
    assert tracker.price_for("jev", "jev").input == 0.042


def test_equal_length_patterns_resolve_deterministically(make: Make) -> None:
    prices = {"a/*": {"input": 1.0, "output": 1.0}, "*/b": {"input": 2.0, "output": 2.0}}
    assert make(prices).price_for("a", "b").input == make(prices).price_for("a", "b").input


# --- arithmetic ----------------------------------------------------------------------------------


def test_cost_is_tokens_times_price_per_million(make: Make) -> None:
    tracker = make(PRICES, max_usd_per_run=100.0)
    tracker.record("openai", "gpt-6-luna", Usage(tokens_in=1_000_000, tokens_out=500_000))
    assert tracker.summary().usd == 0.35  # 0.10 + 0.5 * 0.50


def test_dollar_totals_do_not_drift(make: Make) -> None:
    """1000 calls of one token at $0.10 per million must sum to exactly $0.0001."""
    tracker = make(PRICES, max_usd_per_run=100.0, max_llm_calls_per_run=5000)
    for _ in range(1000):
        tracker.record("openai", "gpt-6-luna", Usage(tokens_in=1, tokens_out=0))
    assert tracker.summary().usd == 0.0001 and tracker.summary().tokens_in == 1000


def test_summary_counts_calls_tokens_cache_hits_and_decider_calls(make: Make) -> None:
    tracker = make(PRICES, max_usd_per_run=100.0)
    tracker.record("groq", "m", Usage(tokens_in=10, tokens_out=4))
    tracker.record("groq", "m", Usage(tokens_in=5, tokens_out=1))
    tracker.record("groq", "m", Usage(tokens_in=999, tokens_out=999), cached=True)
    tracker.record("openai", "gpt-6-luna", Usage(tokens_in=100), kind="decider")
    s = tracker.summary()
    assert (s.llm_calls, s.cache_hits, s.decider_calls) == (2, 1, 1)
    assert (s.tokens_in, s.tokens_out) == (115, 5)  # the cache hit adds no tokens


def test_a_cache_hit_costs_nothing_and_needs_no_price(make: Make) -> None:
    tracker = make(PRICES)
    tracker.record("openai", "gpt-6-luna", Usage(tokens_in=10**9), cached=True)
    assert tracker.summary().usd == 0.0 and tracker.summary().llm_calls == 0


def test_a_fresh_tracker_is_all_zero(make: Make) -> None:
    s = make().summary()
    assert (s.llm_calls, s.cache_hits, s.tokens_in, s.tokens_out, s.decider_calls, s.usd) == (
        0,
    ) * 6


# --- budgets (task 4.6 done-when) ----------------------------------------------------------------


def test_the_call_limit_stops_the_run_before_the_extra_call(make: Make) -> None:
    tracker = make(PRICES, max_llm_calls_per_run=3)
    for _ in range(3):
        tracker.ensure_budget("groq", "m")
        tracker.record("groq", "m", Usage())
    with pytest.raises(BudgetExceededError, match=r"max_llm_calls_per_run \(3\)"):
        tracker.ensure_budget("groq", "m")


def test_recording_a_call_over_the_limit_raises(make: Make) -> None:
    tracker = make(PRICES, max_llm_calls_per_run=1, max_usd_per_run=100.0)
    tracker.record("groq", "m", Usage())
    with pytest.raises(BudgetExceededError, match="made 2 LLM calls"):
        tracker.record("groq", "m", Usage())


def test_the_dollar_limit_stops_the_run_after_the_call_that_crossed_it(make: Make) -> None:
    tracker = make(PRICES, max_usd_per_run=0.50)
    tracker.ensure_budget("openai", "gpt-other")
    with pytest.raises(BudgetExceededError, match=r"cost \$1\.000000, above cost\.max_usd_per_run"):
        tracker.record("openai", "gpt-other", Usage(tokens_in=1_000_000))
    with pytest.raises(BudgetExceededError, match=r"reached cost\.max_usd_per_run"):
        tracker.ensure_budget("openai", "gpt-other")  # and nothing further is allowed


def test_spending_exactly_the_limit_is_allowed_but_the_next_call_is_not(make: Make) -> None:
    tracker = make(PRICES, max_usd_per_run=1.0)
    tracker.record("openai", "gpt-other", Usage(tokens_in=1_000_000))  # exactly $1.00
    with pytest.raises(BudgetExceededError):
        tracker.ensure_budget("openai", "gpt-other")


def test_a_zero_dollar_budget_still_allows_free_providers(make: Make) -> None:
    tracker = make(PRICES, max_usd_per_run=0.0, max_llm_calls_per_run=100)
    for _ in range(5):
        tracker.ensure_budget("groq", "m")
        tracker.record("groq", "m", Usage(tokens_in=10**6, tokens_out=10**6))
    with pytest.raises(BudgetExceededError):
        tracker.record("openai", "gpt-other", Usage(tokens_in=1))  # the first paid token trips it


def test_decider_calls_do_not_count_toward_the_llm_call_limit(make: Make) -> None:
    tracker = make(PRICES, max_llm_calls_per_run=2, max_usd_per_run=100.0)
    for _ in range(10):
        tracker.record("groq", "m", Usage(), kind="decider")
    tracker.ensure_budget("groq", "m")
    assert tracker.summary().decider_calls == 10 and tracker.summary().llm_calls == 0


def test_ensure_budget_rejects_an_unpriced_model_before_any_call(make: Make) -> None:
    with pytest.raises(ConfigError, match="no price for"):
        make(PRICES).ensure_budget("unknown", "model")


def test_the_warning_appears_once_when_a_limit_is_80_percent_used(
    make: Make, caplog: pytest.LogCaptureFixture
) -> None:
    tracker = make(PRICES, max_llm_calls_per_run=10, max_usd_per_run=100.0, warn_at_fraction=0.8)
    with caplog.at_level(logging.WARNING):
        for _ in range(7):
            tracker.record("groq", "m", Usage())
        assert "budget warning" not in caplog.text
        for _ in range(3):
            tracker.record("groq", "m", Usage())
    warnings = [r for r in caplog.records if "budget warning" in r.message]
    assert len(warnings) == 1 and "8 of 10 LLM calls" in warnings[0].message


def test_the_dollar_warning_appears_once_too(make: Make, caplog: pytest.LogCaptureFixture) -> None:
    tracker = make(PRICES, max_usd_per_run=1.0, warn_at_fraction=0.5, max_llm_calls_per_run=100)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            tracker.record("openai", "gpt-other", Usage(tokens_in=200_000))  # $0.20 each
    assert (
        len([r for r in caplog.records if "budget warning" in r.message and "cost $" in r.message])
        == 1
    )


def test_threads_can_record_concurrently_without_losing_updates(make: Make) -> None:
    tracker = make(PRICES, max_usd_per_run=100.0, max_llm_calls_per_run=10_000)

    def work() -> None:
        for _ in range(200):
            tracker.record("openai", "gpt-6-luna", Usage(tokens_in=10, tokens_out=2))

    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    s = tracker.summary()
    assert (s.llm_calls, s.tokens_in, s.tokens_out) == (1600, 16_000, 3_200)
    assert s.usd == 0.0032  # 16000 * 0.10 / 1e6 + 3200 * 0.50 / 1e6


def test_record_cache_hit_counts_without_cost_or_calls(make: Make) -> None:
    tracker = make(PRICES)
    tracker.record_cache_hit()
    tracker.record_cache_hit()
    s = tracker.summary()
    assert (s.cache_hits, s.llm_calls, s.usd) == (2, 0, 0.0)


def test_cost_of_is_exact_rounded_and_does_not_change_the_totals(make: Make) -> None:
    tracker = make(PRICES)
    assert (
        tracker.cost_of("openai", "gpt-6-luna", Usage(tokens_in=1_000_000, tokens_out=500_000))
        == 0.35
    )
    assert tracker.cost_of("openai", "gpt-6-luna", Usage(tokens_in=1)) == 1e-07  # 0.10 / 1e6
    assert tracker.cost_of("openai", "gpt-6-luna", Usage(tokens_in=1, tokens_out=1)) == 6e-07
    assert tracker.cost_of("groq", "m", Usage(tokens_in=10**9, tokens_out=10**9)) == 0.0
    assert tracker.summary().usd == 0.0 and tracker.summary().llm_calls == 0


def test_cost_of_agrees_with_what_record_adds(make: Make) -> None:
    tracker = make(PRICES, max_usd_per_run=100.0)
    usage = Usage(tokens_in=123_456, tokens_out=7_890)
    expected = tracker.cost_of("openai", "gpt-other", usage)
    tracker.record("openai", "gpt-other", usage)
    assert tracker.summary().usd == pytest.approx(expected, abs=1e-6)


def test_cost_of_needs_a_price(make: Make) -> None:
    with pytest.raises(ConfigError, match="no price for"):
        make(PRICES).cost_of("unknown", "m", Usage())
