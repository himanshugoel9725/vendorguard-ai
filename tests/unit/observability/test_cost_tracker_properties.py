"""Seeded property tests of the cost tracker against an independent Decimal reference."""

import logging
import random
import threading
from collections.abc import Callable
from decimal import Decimal
from fnmatch import fnmatchcase

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.providers import CostSettings
from vendorguard.errors import BudgetExceededError
from vendorguard.models.llm import Usage
from vendorguard.observability.cost_tracker import CostTracker

Make = Callable[..., CostTracker]
PRICE_POOL = [0.0, 0.042, 0.0000001, 0.15, 1.0, 2.5, 7.77, 60.0]


@pytest.fixture
def make(settings_override: Callable[..., Settings]) -> Make:
    cache: dict[str, CostSettings] = {}

    def build(prices: dict, **cost: object) -> CostTracker:  # type: ignore[type-arg]
        key = repr(sorted(cost.items()))
        if key not in cache:
            cache[key] = settings_override(cost=dict(cost)).cost
        base = cache[key]
        merged = {**base.model_dump(), "prices_per_million_tokens": prices}
        return CostTracker(CostSettings.model_validate(merged))

    return build


def _prices(rng: random.Random) -> dict[str, dict[str, float]]:
    return {
        f"prov{i}/*": {"input": rng.choice(PRICE_POOL), "output": rng.choice(PRICE_POOL)}
        for i in range(4)
    }


def test_random_sequence_matches_decimal_reference(make: Make) -> None:
    rng = random.Random(2024)
    prices = _prices(rng)
    tracker = make(prices, max_usd_per_run=1e9, max_llm_calls_per_run=10_000, warn_at_fraction=1.0)
    usd, calls, deciders, hits, tin, tout = Decimal(0), 0, 0, 0, 0, 0
    for _ in range(500):
        prov = f"prov{rng.randrange(4)}"
        usage = Usage(tokens_in=rng.randint(0, 10**6), tokens_out=rng.randint(0, 10**6))
        cached, kind = rng.random() < 0.2, rng.choice(["llm", "decider"])
        tracker.record(prov, "m", usage, cached=cached, kind=kind)  # type: ignore[arg-type]
        if cached:
            hits += 1
            continue
        p = prices[f"{prov}/*"]
        usd += (
            usage.tokens_in * Decimal(str(p["input"]))
            + usage.tokens_out * Decimal(str(p["output"]))
        ) / 1_000_000
        calls, deciders = calls + (kind == "llm"), deciders + (kind == "decider")
        tin, tout = tin + usage.tokens_in, tout + usage.tokens_out
    s = tracker.summary()
    assert (s.llm_calls, s.decider_calls, s.cache_hits) == (calls, deciders, hits)
    assert (s.tokens_in, s.tokens_out) == (tin, tout)
    assert s.usd == round(float(usd), 6) and isinstance(s.usd, float)


def test_cached_records_never_change_counters_except_hits(make: Make) -> None:
    tracker = make({"p/*": {"input": 5.0, "output": 5.0}})
    tracker.record("p", "m", Usage(tokens_in=10, tokens_out=10))
    before = tracker.summary()
    for _ in range(50):
        tracker.record("p", "m", Usage(tokens_in=10**9, tokens_out=10**9), cached=True)
    after = tracker.summary()
    assert after.cache_hits == 50
    assert after.model_copy(update={"cache_hits": 0}) == before.model_copy(update={"cache_hits": 0})


def test_ensure_budget_keeps_raising_once_it_raised(make: Make) -> None:
    tracker = make({"p/*": {"input": 1.0, "output": 1.0}}, max_usd_per_run=1.0)
    with pytest.raises(BudgetExceededError):
        tracker.record("p", "m", Usage(tokens_in=2_000_000))
    for _ in range(5):
        with pytest.raises(BudgetExceededError):
            tracker.ensure_budget("p", "m")
        with pytest.raises(BudgetExceededError):
            tracker.ensure_budget("p", "m", "decider")


def test_ensure_budget_never_changes_counters(make: Make) -> None:
    tracker = make({"p/*": {"input": 1.0, "output": 1.0}})
    tracker.record("p", "m", Usage(tokens_in=5, tokens_out=6))
    before = tracker.summary()
    for _ in range(20):
        tracker.ensure_budget("p", "m")
    assert tracker.summary() == before


@pytest.mark.parametrize("fraction", [1.0, 0.5])
def test_warns_once_for_usd_and_once_for_calls(
    make: Make, caplog: pytest.LogCaptureFixture, fraction: float
) -> None:
    tracker = make(
        {"p/*": {"input": 1.0, "output": 0.0}},
        max_usd_per_run=10.0,
        max_llm_calls_per_run=1000,
        warn_at_fraction=fraction,
    )
    with caplog.at_level(logging.WARNING, logger="vendorguard.observability.cost_tracker"):
        for _ in range(10):
            tracker.record("p", "m", Usage(tokens_in=1_000_000))  # $1 each: 10 calls = limit
    warnings = [r.getMessage() for r in caplog.records if "budget warning" in r.getMessage()]
    assert len(warnings) == 1 and "cost $" in warnings[0]
    assert f"warn_at_fraction={fraction:g}" in warnings[0]


def test_zero_usd_limit_with_free_providers_never_raises(make: Make) -> None:
    tracker = make({"p/*": {"input": 0.0, "output": 0.0}}, max_usd_per_run=0.0)
    for _ in range(100):
        tracker.ensure_budget("p", "m")
        tracker.record("p", "m", Usage(tokens_in=10**9, tokens_out=10**9))
    assert tracker.summary().usd == 0.0


def test_price_for_matches_a_fnmatch_reference(make: Make) -> None:
    rng = random.Random(77)
    atoms = ["a", "b", "ab", "x/y", "*", "?"]
    for _ in range(100):
        patterns = {"".join(rng.choices(atoms, k=rng.randint(1, 4))) for _ in range(6)}
        patterns.add("*")
        prices = {p: {"input": float(i), "output": 0.0} for i, p in enumerate(sorted(patterns))}
        tracker = make(prices)
        for _ in range(10):
            name = "".join(rng.choices("ab/xy", k=rng.randint(2, 6)))
            provider, _, model = name.partition("/")
            if not model:
                provider, model = name, "m"
            full = f"{provider}/{model}"
            matches = [p for p in prices if fnmatchcase(full, p)]
            best = max(matches, key=lambda p: (len(p.replace("*", "")), p))
            assert tracker.price_for(provider, model).input == prices[best]["input"]


def test_16_threads_by_500_records_give_exact_totals(make: Make) -> None:
    tracker = make(
        {"p/*": {"input": 0.042, "output": 0.0000001}},
        max_usd_per_run=1e9,
        max_llm_calls_per_run=100_000,
        warn_at_fraction=1.0,
    )
    errors: list[BaseException] = []

    def work() -> None:
        try:
            for _ in range(500):
                tracker.record("p", "m", Usage(tokens_in=1000, tokens_out=3))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    s = tracker.summary()
    assert (s.llm_calls, s.tokens_in, s.tokens_out) == (8000, 8_000_000, 24_000)
    expected = (8_000_000 * Decimal("0.042") + 24_000 * Decimal("0.0000001")) / 1_000_000
    assert s.usd == round(float(expected), 6)


def test_tiny_and_huge_token_counts_keep_precision(make: Make) -> None:
    tracker = make(
        {"p/*": {"input": 0.0000001, "output": 60.0}},
        max_usd_per_run=1e12,
        max_llm_calls_per_run=100,
        warn_at_fraction=1.0,
    )
    tracker.record("p", "m", Usage(tokens_in=1, tokens_out=0))
    assert tracker.summary().usd == 0.0  # 1e-13 rounds to 0 at 6 decimals
    tracker.record("p", "m", Usage(tokens_in=10**12, tokens_out=10**12))
    s = tracker.summary()
    assert (s.tokens_in, s.tokens_out) == (10**12 + 1, 10**12)
    expected = (Decimal(10**12 + 1) * Decimal("0.0000001") + Decimal(10**12) * 60) / 1_000_000
    assert s.usd == round(float(expected), 6)
