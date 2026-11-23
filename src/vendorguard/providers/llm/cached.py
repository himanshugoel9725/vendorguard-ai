"""Record/replay cache around any LLM client: ``off``, ``read_write`` or ``read_only``."""

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from vendorguard.config_models.base import CacheMode
from vendorguard.errors import CacheMissError
from vendorguard.interfaces.cache import CacheBackend
from vendorguard.interfaces.llm import LLMClient
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.providers.cache.keys import llm_key

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger(__name__)


class CachedLLM:
    """Answers repeated calls from the cache.

    * ``off``: the cache is not consulted and nothing is stored.
    * ``read_write``: a hit is replayed, a miss calls the client and records the answer.
    * ``read_only``: a hit is replayed, a miss raises ``CacheMissError`` (CI and the demo site).

    A replayed result has ``cached=True`` and zero token usage, so it costs nothing. ``hits`` and
    ``misses`` count cache lookups (not touched in ``off`` mode).
    """

    def __init__(
        self,
        inner: LLMClient,
        cache: CacheBackend | None,
        mode: CacheMode,
        params: Mapping[str, Any],
        on_hit: Callable[[], None] | None = None,
    ) -> None:
        self.provider = inner.provider
        self.model = inner.model
        self.hits = 0
        self.misses = 0
        self._inner = inner
        self._cache = cache
        self._mode: CacheMode = mode if cache is not None else "off"
        self._params = dict(params)
        self._on_hit = on_hit

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[T],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[T]:
        """Replay the recorded answer, or ask the wrapped client (never in ``read_only`` mode)."""
        if self._cache is None or self._mode == "off":
            return self._inner.complete_json(messages, output_model, purpose=purpose, hints=hints)
        key = llm_key(
            provider=self.provider,
            model=self.model,
            purpose=purpose,
            messages=messages,
            schema=output_model.model_json_schema(),
            params=self._params,
            hints=hints,
        )
        replay = self._replay(key, output_model)
        if replay is not None:
            self.hits += 1
            if self._on_hit:
                self._on_hit()
            return replay
        self.misses += 1
        if self._mode == "read_only":
            raise CacheMissError(
                f"no recorded answer for a '{purpose}' call (cache is read-only): run make record"
            )
        result = self._inner.complete_json(messages, output_model, purpose=purpose, hints=hints)
        entry = {
            "parsed": result.parsed.model_dump(mode="json"),
            "usage": result.usage.model_dump(),
            "provider": result.provider,
            "model": result.model,
        }
        try:
            self._cache.put(key, entry, purpose=purpose)
        except Exception as exc:  # the answer is already paid for: a cache problem must not lose it
            log.warning("could not cache an LLM answer (%s)", type(exc).__name__)
        return result

    def _replay(self, key: str, output_model: type[T]) -> LLMResult[T] | None:
        assert self._cache is not None  # noqa: S101  (callers check)
        entry = self._cache.get(key)
        if entry is None:
            return None
        try:
            parsed = output_model.model_validate(entry["parsed"])
        except (KeyError, ValidationError):
            return None  # a damaged or outdated entry counts as a miss
        return LLMResult[T](
            parsed=parsed,
            usage=Usage(),
            provider=self.provider,
            model=self.model,
            cached=True,
            latency_ms=0.0,
        )


__all__ = ["CachedLLM"]
