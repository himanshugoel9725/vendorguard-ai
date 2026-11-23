"""Applies the run's budget guard to any LLM client."""

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from vendorguard.interfaces.llm import LLMClient
from vendorguard.models.llm import ChatMessage, LLMResult
from vendorguard.observability.cost_tracker import CostTracker

T = TypeVar("T", bound=BaseModel)


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
        """Stop before a call that the budget no longer allows; account for the one just made."""
        self._tracker.ensure_budget(self.provider, self.model)
        result = self._inner.complete_json(messages, output_model, purpose=purpose, hints=hints)
        self._tracker.record(self.provider, self.model, result.usage, cached=result.cached)
        return result


__all__ = ["BudgetedLLM"]
