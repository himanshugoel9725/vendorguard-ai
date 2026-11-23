"""Cost and call accounting for one run, with hard budget limits (``cost.*`` in settings)."""

import logging
import threading
from decimal import Decimal
from fnmatch import fnmatchcase
from typing import Literal

from vendorguard.config_models.providers import CostSettings, PriceSettings
from vendorguard.errors import BudgetExceededError, ConfigError
from vendorguard.models.llm import Usage
from vendorguard.models.run import CostSummary

log = logging.getLogger(__name__)
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)  # prices are per million tokens
USD_DECIMALS = 6
Kind = Literal["llm", "decider"]


class CostTracker:
    """Counts calls, tokens and dollars; stops the run before and after it overspends.

    Dollars are summed as exact decimals so the totals do not depend on float rounding.
    Cache hits are counted separately and cost nothing. Safe to share between threads.
    """

    def __init__(self, settings: CostSettings) -> None:
        self._s = settings
        self._lock = threading.Lock()
        self._usd = Decimal(0)
        self._calls = {"llm": 0, "decider": 0}
        self._tokens_in = 0
        self._tokens_out = 0
        self._cache_hits = 0
        self._warned: set[str] = set()

    def price_for(self, provider: str, model: str) -> PriceSettings:
        """The price of ``provider/model``: the most specific matching pattern wins.

        Raises ConfigError when nothing matches, so a paid model can never run unpriced.
        """
        name = f"{provider}/{model}"
        matches = [p for p in self._s.prices_per_million_tokens if fnmatchcase(name, p)]
        if not matches:
            raise ConfigError(
                f"no price for '{name}': add it to cost.prices_per_million_tokens (0 if it is free)"
            )
        best = max(matches, key=lambda p: (len(p.replace("*", "")), p))
        return self._s.prices_per_million_tokens[best]

    def ensure_budget(self, provider: str, model: str, kind: Kind = "llm") -> None:
        """Call before a model call: the model must be priced and the budget not yet used up."""
        self.price_for(provider, model)
        with self._lock:
            if kind == "llm" and self._calls["llm"] >= self._s.max_llm_calls_per_run:
                raise BudgetExceededError(
                    f"the run reached cost.max_llm_calls_per_run ({self._s.max_llm_calls_per_run})"
                )
            if self._usd > 0 and self._usd >= Decimal(str(self._s.max_usd_per_run)):
                raise BudgetExceededError(
                    f"the run reached cost.max_usd_per_run (${self._s.max_usd_per_run:g})"
                )

    def record(
        self, provider: str, model: str, usage: Usage, *, cached: bool = False, kind: Kind = "llm"
    ) -> None:
        """Add one finished call. Raises BudgetExceededError if it pushed the run over a limit."""
        price = self.price_for(provider, model)
        with self._lock:
            if cached:
                self._cache_hits += 1
                return
            self._calls[kind] += 1
            self._tokens_in += usage.tokens_in
            self._tokens_out += usage.tokens_out
            cost = (
                usage.tokens_in * Decimal(str(price.input))
                + usage.tokens_out * Decimal(str(price.output))
            ) / TOKENS_PER_PRICE_UNIT
            self._usd += cost
            self._check_after_call()

    def record_cache_hit(self) -> None:
        """Count an answer that was replayed from the cache (free, and not a call)."""
        with self._lock:
            self._cache_hits += 1

    def summary(self) -> CostSummary:
        """The totals so far."""
        with self._lock:
            return CostSummary(
                llm_calls=self._calls["llm"],
                cache_hits=self._cache_hits,
                tokens_in=self._tokens_in,
                tokens_out=self._tokens_out,
                decider_calls=self._calls["decider"],
                usd=round(float(self._usd), USD_DECIMALS),
            )

    def _check_after_call(self) -> None:
        limit_usd = Decimal(str(self._s.max_usd_per_run))
        if self._usd > limit_usd:
            raise BudgetExceededError(
                f"the run cost ${float(self._usd):.6f}, above cost.max_usd_per_run "
                f"(${self._s.max_usd_per_run:g})"
            )
        if self._calls["llm"] > self._s.max_llm_calls_per_run:
            raise BudgetExceededError(
                f"the run made {self._calls['llm']} LLM calls, above "
                f"cost.max_llm_calls_per_run ({self._s.max_llm_calls_per_run})"
            )
        fraction = Decimal(str(self._s.warn_at_fraction))
        if self._usd > 0 and self._usd >= limit_usd * fraction:
            self._warn("usd", f"cost ${float(self._usd):.6f} of ${self._s.max_usd_per_run:g}")
        if self._calls["llm"] >= self._s.max_llm_calls_per_run * float(fraction):
            self._warn(
                "calls", f"{self._calls['llm']} of {self._s.max_llm_calls_per_run} LLM calls"
            )

    def _warn(self, which: str, text: str) -> None:
        if which not in self._warned:
            self._warned.add(which)
            log.warning("budget warning: %s (warn_at_fraction=%g)", text, self._s.warn_at_fraction)


__all__ = ["CostTracker"]
