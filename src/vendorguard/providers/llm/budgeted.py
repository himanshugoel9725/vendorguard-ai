"""Applies the run's budget guard to any LLM client."""

import logging
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from vendorguard.errors import BudgetExceededError, VendorGuardError
from vendorguard.interfaces.llm import LLMClient
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.observability.cost_tracker import CostTracker

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)


class BudgetedLLM:
    """Checks the budget before every call and records the cost after it.

    Put it directly around the real client and the cache around it:
    ``CachedLLM(BudgetedLLM(client, tracker), cache, mode, params,``
    ``on_hit=tracker.record_cache_hit)``.
    Then only real calls are checked and paid for, and replays still work when the budget is spent.
    """

    def __init__(self, inner: LLMClient, tracker: CostTracker) -> None:
        self.provider = inner.provider
        self.model = inner.model
        self._inner = inner
        self._tracker = tracker

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[T],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[T]:
        """Stop before a call that the budget no longer allows; account for the one just made.

        Money already spent is always charged: a call that fails after paid attempts (for example
        invalid replies that were re-asked) is charged with those tokens, and a call that crosses a
        limit still returns its answer, so it can be cached instead of bought twice. The run then
        stops at the next call, which ``ensure_budget`` refuses.
        """
        self._tracker.ensure_budget(self.provider, self.model)
        try:
            result = self._inner.complete_json(messages, output_model, purpose=purpose, hints=hints)
        except VendorGuardError as exc:
            if exc.paid_usage:
                self._charge(
                    Usage(tokens_in=exc.paid_usage[0], tokens_out=exc.paid_usage[1]), False
                )
            raise
        self._charge(result.usage, result.cached)
        return result

    def _charge(self, usage: Usage, cached: bool) -> None:
        try:
            self._tracker.record(self.provider, self.model, usage, cached=cached)
        except BudgetExceededError as exc:
            log.warning("%s; the next call will be refused", exc)


__all__ = ["BudgetedLLM"]
