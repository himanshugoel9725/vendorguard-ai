"""The only place where concrete providers are created (registries: config name -> builder).

Adding an implementation is one builder here, one name in ``config_models/base.py`` and one
settings block (``/add-provider``). Everything else depends on the protocols in ``interfaces/``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vendorguard.config import Settings
from vendorguard.config_models.providers import CacheSettings
from vendorguard.errors import ConfigError
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.cache import CacheBackend
from vendorguard.interfaces.decider import Decider
from vendorguard.interfaces.embedder import Embedder
from vendorguard.interfaces.llm import LLMClient
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.cache.jsonl_cache import JsonlCache
from vendorguard.providers.cache.sqlite_cache import SqliteCache
from vendorguard.providers.decide.fallback import FallbackDecider
from vendorguard.providers.decide.jev import JevDecider
from vendorguard.providers.decide.jev_client import JevClient
from vendorguard.providers.decide.llm_judge import LlmJudgeDecider
from vendorguard.providers.decide.mock import MockDecider
from vendorguard.providers.decide.rule import RuleDecider
from vendorguard.providers.embed.cached import CachedEmbedder
from vendorguard.providers.embed.null import NullEmbedder
from vendorguard.providers.embed.ollama import OllamaEmbedder
from vendorguard.providers.llm.budgeted import BudgetedLLM
from vendorguard.providers.llm.cached import CachedLLM
from vendorguard.providers.llm.mock import MockLLM
from vendorguard.providers.llm.ollama import OllamaLLM
from vendorguard.providers.llm.openai_compat import OpenAICompatLLM
from vendorguard.providers.memory.sqlite_store import SqliteMemoryStore
from vendorguard.utils.prompt_loader import PromptLoader

Builder = Callable[[Settings], Any]


def _hosted(name: str) -> Callable[[Settings], LLMClient]:
    return lambda s: OpenAICompatLLM(name, s.llm, getattr(s.llm, name))


LLM_PROVIDERS: dict[str, Callable[[Settings], LLMClient]] = {
    "ollama": lambda s: OllamaLLM(s.llm),
    "openai": _hosted("openai"),
    "groq": _hosted("groq"),
    "openai_compat": _hosted("openai_compat"),
    "mock": lambda s: MockLLM(s.decision.rule),
}
EMBEDDERS: dict[str, Callable[[Settings], Embedder]] = {
    "ollama": lambda s: OllamaEmbedder(s.embeddings),
    "none": lambda s: NullEmbedder(),
}
CACHE_BACKENDS: dict[str, Callable[[CacheSettings], CacheBackend]] = {
    "sqlite": lambda c: SqliteCache(c.sqlite_path),
    "jsonl": lambda c: JsonlCache(c.jsonl_dir),
}


@dataclass(frozen=True)
class DeciderDeps:
    """What a model-backed decider needs besides the settings (the rule decider needs none)."""

    llm: LLMClient
    prompts: PromptLoader
    audit: AuditSink
    cost: CostTracker


def _llm_judge(s: Settings, deps: DeciderDeps | None) -> Decider:
    if deps is None:
        raise ConfigError(
            "the llm_judge decider needs an LLM, prompts, an audit sink and a cost tracker"
        )
    judge = LlmJudgeDecider(deps.llm, deps.prompts, deps.audit, deps.cost, s.decision.rule)
    # A failing judge (model or schema error) must never stop a run: the rules take over.
    return FallbackDecider(
        judge, RuleDecider(s.decision.rule), deps.audit, primary_name="llm_judge"
    )


def _jev(s: Settings, deps: DeciderDeps | None) -> Decider:
    if deps is None:
        raise ConfigError("the jev decider needs an audit sink and a cost tracker")
    fallback = _lookup(DECIDERS, s.decision.jev.fallback_provider, "decision")(s, deps)
    if not s.decision.jev.api_key.get_secret_value():
        return FallbackDecider(
            None, fallback, deps.audit, primary_name="jev",
            unavailable="no key: set VG_DECISION__JEV__API_KEY in .env",
        )  # fmt: skip
    jev = JevDecider(JevClient(s.decision.jev, s.llm), s.decision.jev, deps.audit, deps.cost)
    return FallbackDecider(jev, fallback, deps.audit, primary_name="jev")


DECIDERS: dict[str, Callable[[Settings, DeciderDeps | None], Decider]] = {
    "rule": lambda s, _deps: RuleDecider(s.decision.rule),
    "mock": lambda s, _deps: MockDecider(s.decision.rule),
    "llm_judge": _llm_judge,
    "jev": _jev,
}
MEMORY_STORES: dict[str, Callable[[Settings], MemoryStore]] = {
    "sqlite": lambda s: SqliteMemoryStore(
        s.memory.sqlite_path, s.memory.busy_timeout_s
    ),  # letta: task 7.5
}

UNCACHED_LLM_PROVIDERS = frozenset({"mock"})  # the mock is free and deterministic: never cached
UNBUDGETED_LLM_PROVIDERS = frozenset({"mock"})  # ... and never counted or capped (0 LLM calls)
UNCACHED_EMBEDDERS = frozenset({"none"})


@dataclass(frozen=True)
class Providers:
    """The providers of one run. Call ``close()`` at the end (it saves recorded cassettes)."""

    llm: LLMClient
    embedder: Embedder
    cache: CacheBackend | None
    tracker: CostTracker
    closers: tuple[Callable[[], None], ...]

    def close(self) -> None:
        """Close HTTP clients and the cache (a JSONL cache writes its sorted cassettes here)."""
        for close in self.closers:
            close()


def _lookup[T](registry: dict[str, T], name: str, kind: str) -> T:
    if name not in registry:
        raise ConfigError(
            f"{kind} provider '{name}' is not implemented yet (available: {sorted(registry)})"
        )
    return registry[name]


def llm_cache_params(settings: Settings) -> dict[str, Any]:
    """Everything besides the messages that can change an LLM's answer (part of the cache key)."""
    llm = settings.llm
    params: dict[str, Any] = {
        "temperature": llm.temperature,
        "seed": llm.seed,
        "top_p": llm.top_p,
        "max_output_tokens": llm.max_output_tokens,
        "context_window": llm.context_window,
        "json_repair_attempts": llm.json_repair_attempts,  # changes the answer when a reply is bad
    }
    if llm.provider in ("openai", "groq", "openai_compat"):
        profile = getattr(llm, llm.provider)
        params |= {
            "response_format": profile.response_format,
            "max_tokens_field": profile.max_tokens_field,
            "omit_params": sorted(profile.omit_params),
        }
    return params


def build_cache(settings: Settings) -> CacheBackend | None:
    """The configured cache backend, or ``None`` when ``cache.enabled`` is false."""
    if not settings.cache.enabled:
        return None
    return _lookup(CACHE_BACKENDS, settings.cache.backend, "cache backend")(settings.cache)


def build_decider(settings: Settings, deps: DeciderDeps | None = None) -> Decider:
    """The configured decider (rule, llm_judge, jev, mock); model-backed ones need ``deps``."""
    return _lookup(DECIDERS, settings.decision.provider, "decision")(settings, deps)


def build_memory_store(settings: Settings) -> MemoryStore:
    """The configured memory store (sqlite now, letta in 7.5). Close it with ``.close()``."""
    return _lookup(MEMORY_STORES, settings.memory.provider, "memory")(settings)


def build_providers(settings: Settings) -> Providers:
    """Create the LLM, embedder, cache and cost tracker of a run and nest them correctly.

    LLM: ``CachedLLM(BudgetedLLM(client))``, so only real calls are checked and paid and replays
    still work after the budget is spent. Embeddings: ``CachedEmbedder(client)``. The mock LLM is
    neither cached nor budgeted (free, deterministic, not counted as an LLM call) and the ``none``
    embedder is never cached.
    """
    tracker = CostTracker(settings.cost)
    cache = build_cache(settings)
    closers: list[Callable[[], None]] = []
    raw_llm = _lookup(LLM_PROVIDERS, settings.llm.provider, "LLM")(settings)
    raw_embedder = _lookup(EMBEDDERS, settings.embeddings.provider, "embeddings")(settings)
    for client in (raw_llm, raw_embedder):
        if hasattr(client, "close"):
            closers.append(client.close)
    llm: LLMClient = raw_llm
    if settings.llm.provider not in UNBUDGETED_LLM_PROVIDERS:
        llm = BudgetedLLM(raw_llm, tracker)
    embedder = raw_embedder
    if cache is not None:
        mode = settings.cache.mode
        if settings.llm.provider not in UNCACHED_LLM_PROVIDERS:
            llm = CachedLLM(
                llm, cache, mode, llm_cache_params(settings), on_hit=tracker.record_cache_hit
            )
        if settings.embeddings.provider not in UNCACHED_EMBEDDERS:
            e = settings.embeddings
            embedder = CachedEmbedder(raw_embedder, cache, e.doc_prefix, e.query_prefix, mode=mode)
        if hasattr(cache, "close"):
            closers.append(cache.close)
    return Providers(
        llm=llm, embedder=embedder, cache=cache, tracker=tracker, closers=tuple(closers)
    )


__all__ = [
    "CACHE_BACKENDS",
    "DECIDERS",
    "DeciderDeps",
    "EMBEDDERS",
    "LLM_PROVIDERS",
    "MEMORY_STORES",
    "Providers",
    "build_cache",
    "build_decider",
    "build_memory_store",
    "build_providers",
    "llm_cache_params",
]
