"""Factory: registries match the config, every entry builds, and the nesting is right."""

from collections.abc import Callable
from pathlib import Path
from typing import get_args

import httpx
import pytest
import respx
from pydantic import BaseModel

from vendorguard import factory
from vendorguard.config import Settings
from vendorguard.config_models import base
from vendorguard.errors import CacheMissError, ConfigError
from vendorguard.models.finding import DraftFinding
from vendorguard.models.llm import ChatMessage
from vendorguard.providers.cache.jsonl_cache import JsonlCache
from vendorguard.providers.cache.sqlite_cache import SqliteCache
from vendorguard.providers.embed.cached import CachedEmbedder
from vendorguard.providers.embed.null import NullEmbedder
from vendorguard.providers.embed.ollama import OllamaEmbedder
from vendorguard.providers.llm.budgeted import BudgetedLLM
from vendorguard.providers.llm.cached import CachedLLM
from vendorguard.providers.llm.mock import MockLLM
from vendorguard.providers.llm.ollama import OllamaLLM
from vendorguard.providers.llm.openai_compat import OpenAICompatLLM

Make = Callable[..., Settings]
KEYS = {name: {"api_key": "sk-fake-test-key"} for name in ("openai", "groq", "openai_compat")}


class Out(BaseModel):
    status: str


# --- registries and the config's allowed names (ADR-009) -----------------------------------------


def test_llm_embedding_and_cache_registries_match_the_config_literals_exactly() -> None:
    assert set(factory.LLM_PROVIDERS) == set(get_args(base.LlmProvider))
    assert set(factory.EMBEDDERS) == set(get_args(base.EmbeddingsProvider))
    assert set(factory.CACHE_BACKENDS) == set(get_args(base.CacheBackendName))


def test_decider_and_memory_registries_only_contain_allowed_names() -> None:
    """They fill up in Phase 5 and Phase 7; equality becomes mandatory then (update this test)."""
    assert set(factory.DECIDERS) <= set(get_args(base.DeciderProvider))
    assert set(factory.MEMORY_STORES) <= set(get_args(base.MemoryProvider))


# --- every registered entry builds (task 4.8 done-when) ------------------------------------------


@pytest.mark.parametrize("name", sorted(factory.LLM_PROVIDERS))
def test_every_llm_provider_builds_from_mock_style_settings(
    settings_override: Make, name: str
) -> None:
    client = factory.LLM_PROVIDERS[name](settings_override(llm={"provider": name, **KEYS}))
    assert client.provider == name or (name == "ollama" and client.provider == "ollama")
    assert client.model and callable(client.complete_json)


@pytest.mark.parametrize("name", sorted(factory.EMBEDDERS))
def test_every_embedder_builds(settings_override: Make, name: str) -> None:
    assert factory.EMBEDDERS[name](settings_override(embeddings={"provider": name})).model


@pytest.mark.parametrize("name", sorted(factory.CACHE_BACKENDS))
def test_every_cache_backend_builds(settings_override: Make, name: str) -> None:
    cache = factory.CACHE_BACKENDS[name](settings_override(cache={"backend": name}).cache)
    assert cache.get("missing") is None


@pytest.mark.parametrize("provider", sorted(factory.LLM_PROVIDERS))
def test_build_providers_works_for_every_llm_provider(
    settings_override: Make, provider: str
) -> None:
    providers = factory.build_providers(settings_override(llm={"provider": provider, **KEYS}))
    assert providers.llm.provider == provider
    providers.close()


def test_the_concrete_classes_are_the_expected_ones(settings_override: Make) -> None:
    s = settings_override(llm=KEYS)
    assert isinstance(factory.LLM_PROVIDERS["ollama"](s), OllamaLLM)
    assert isinstance(factory.LLM_PROVIDERS["mock"](s), MockLLM)
    for name in ("openai", "groq", "openai_compat"):
        client = factory.LLM_PROVIDERS[name](s)
        assert isinstance(client, OpenAICompatLLM) and client.provider == name
    assert isinstance(factory.EMBEDDERS["ollama"](s), OllamaEmbedder)
    assert isinstance(factory.EMBEDDERS["none"](s), NullEmbedder)
    assert isinstance(factory.CACHE_BACKENDS["sqlite"](s.cache), SqliteCache)
    assert isinstance(factory.CACHE_BACKENDS["jsonl"](s.cache), JsonlCache)


def test_a_hosted_provider_without_a_key_fails_early_naming_the_variable(
    settings_override: Make,
) -> None:
    with pytest.raises(ConfigError, match="VG_LLM__OPENAI__API_KEY"):
        factory.build_providers(settings_override(llm={"provider": "openai"}))


def test_deciders_and_memory_are_not_implemented_yet_with_a_clear_message(
    settings_override: Make,
) -> None:
    with pytest.raises(ConfigError, match=r"decision provider 'rule' is not implemented yet"):
        factory.build_decider(settings_override())
    with pytest.raises(ConfigError, match=r"memory provider 'sqlite' is not implemented yet"):
        factory.build_memory_store(settings_override())


# --- nesting -------------------------------------------------------------------------------------


def test_the_mock_is_neither_budgeted_nor_cached(settings_override: Make) -> None:
    p = factory.build_providers(settings_override(llm={"provider": "mock"}))
    assert isinstance(p.llm, MockLLM)
    assert not isinstance(p.llm, BudgetedLLM | CachedLLM)


def test_a_real_provider_is_cached_around_the_budget_guard(settings_override: Make) -> None:
    p = factory.build_providers(settings_override(llm={"provider": "ollama"}))
    assert isinstance(p.llm, CachedLLM) and isinstance(p.llm._inner, BudgetedLLM)  # noqa: SLF001
    assert isinstance(p.llm._inner._inner, OllamaLLM)  # noqa: SLF001
    p.close()


def test_disabling_the_cache_leaves_only_the_budget_guard(settings_override: Make) -> None:
    p = factory.build_providers(
        settings_override(llm={"provider": "ollama"}, cache={"enabled": False})
    )
    assert p.cache is None and isinstance(p.llm, BudgetedLLM) and not isinstance(p.llm, CachedLLM)
    assert isinstance(p.embedder, NullEmbedder)


def test_embedders_are_cached_except_the_none_provider(settings_override: Make) -> None:
    none = factory.build_providers(settings_override())
    assert isinstance(none.embedder, NullEmbedder)
    ollama = factory.build_providers(settings_override(embeddings={"provider": "ollama"}))
    assert isinstance(ollama.embedder, CachedEmbedder) and isinstance(
        ollama.embedder._inner, OllamaEmbedder
    )  # noqa: SLF001
    ollama.close()


def test_the_cache_backend_and_mode_come_from_settings(settings_override: Make) -> None:
    sqlite = factory.build_providers(settings_override(llm={"provider": "ollama"}))
    assert isinstance(sqlite.cache, SqliteCache)
    jsonl = factory.build_providers(
        settings_override(
            llm={"provider": "ollama"}, cache={"backend": "jsonl", "mode": "read_only"}
        )
    )
    assert isinstance(jsonl.cache, JsonlCache) and jsonl.llm._mode == "read_only"  # type: ignore[attr-defined]  # noqa: SLF001
    sqlite.close()


def test_cache_params_cover_generation_settings_and_hosted_profile_options(
    settings_override: Make,
) -> None:
    base_params = factory.llm_cache_params(settings_override(llm={"provider": "ollama"}))
    assert set(base_params) == {
        "json_repair_attempts",
        "temperature",
        "seed",
        "top_p",
        "max_output_tokens",
        "context_window",
    }
    assert (
        factory.llm_cache_params(settings_override(llm={"provider": "ollama", "seed": 9}))
        != base_params
    )
    hosted = factory.llm_cache_params(settings_override(llm={"provider": "groq", **KEYS}))
    assert {"response_format", "max_tokens_field", "omit_params"} <= set(hosted)
    changed = factory.llm_cache_params(
        settings_override(
            llm={"provider": "groq", "groq": {"api_key": "x", "response_format": "json_object"}}
        )
    )
    assert changed != hosted


# --- behaviour end to end ------------------------------------------------------------------------


def _reply(content: str = '{"status": "ok"}') -> httpx.Response:
    return httpx.Response(
        200, json={"message": {"content": content}, "prompt_eval_count": 7, "eval_count": 3}
    )


@respx.mock
def test_second_identical_call_is_a_replay_and_the_tracker_sees_both(
    settings_override: Make,
) -> None:
    route = respx.post("http://localhost:11434/api/chat").mock(return_value=_reply())
    p = factory.build_providers(settings_override(llm={"provider": "ollama"}))
    msgs = [ChatMessage(role="user", content="q")]
    first = p.llm.complete_json(msgs, Out, purpose="mapper")
    second = p.llm.complete_json(msgs, Out, purpose="mapper")
    assert (first.cached, second.cached, route.call_count) == (False, True, 1)
    s = p.tracker.summary()
    assert (s.llm_calls, s.cache_hits, s.tokens_in, s.tokens_out, s.usd) == (1, 1, 7, 3, 0.0)
    p.close()


@respx.mock
def test_replays_work_after_the_call_budget_is_spent(settings_override: Make) -> None:
    respx.post("http://localhost:11434/api/chat").mock(return_value=_reply())
    p = factory.build_providers(
        settings_override(llm={"provider": "ollama"}, cost={"max_llm_calls_per_run": 1})
    )
    msgs = [ChatMessage(role="user", content="q")]
    p.llm.complete_json(msgs, Out, purpose="mapper")
    assert p.llm.complete_json(msgs, Out, purpose="mapper").cached
    from vendorguard.errors import BudgetExceededError

    with pytest.raises(BudgetExceededError):
        p.llm.complete_json([ChatMessage(role="user", content="new")], Out, purpose="mapper")
    p.close()


@respx.mock
def test_record_to_cassettes_then_replay_read_only_without_the_network(
    settings_override: Make, tmp_path: Path
) -> None:
    cassettes = tmp_path / "cassettes"
    route = respx.post("http://localhost:11434/api/chat").mock(return_value=_reply())
    cache = {"backend": "jsonl", "jsonl_dir": cassettes}
    msgs = [ChatMessage(role="user", content="q")]
    recorder = factory.build_providers(
        settings_override(llm={"provider": "ollama"}, cache={**cache, "mode": "read_write"})
    )
    recorder.llm.complete_json(msgs, Out, purpose="mapper")
    recorder.close()  # sorts and saves the cassettes
    assert (cassettes / "mapper.jsonl").exists() and route.call_count == 1
    respx.reset()
    replay = factory.build_providers(
        settings_override(llm={"provider": "ollama"}, cache={**cache, "mode": "read_only"})
    )
    assert replay.llm.complete_json(msgs, Out, purpose="mapper").cached
    with pytest.raises(CacheMissError, match="run make record"):
        replay.llm.complete_json([ChatMessage(role="user", content="other")], Out, purpose="mapper")
    replay.close()


@respx.mock
def test_embeddings_honour_the_cache_mode(settings_override: Make, tmp_path: Path) -> None:
    respx.post("http://localhost:11434/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [[1.0, 2.0]]})
    )
    cache = {"backend": "jsonl", "jsonl_dir": tmp_path / "c"}
    rec = factory.build_providers(
        settings_override(embeddings={"provider": "ollama"}, cache={**cache, "mode": "read_write"})
    )
    assert rec.embedder.embed_documents(["a"]) == [[1.0, 2.0]]
    rec.close()
    ro = factory.build_providers(
        settings_override(embeddings={"provider": "ollama"}, cache={**cache, "mode": "read_only"})
    )
    assert ro.embedder.embed_documents(["a"]) == [[1.0, 2.0]]
    with pytest.raises(CacheMissError):
        ro.embedder.embed_documents(["unseen"])
    with pytest.raises(CacheMissError):
        ro.embedder.embed_query("unseen")
    off = factory.build_providers(
        settings_override(embeddings={"provider": "ollama"}, cache={**cache, "mode": "off"})
    )
    assert off.embedder.embed_query("anything") == [1.0, 2.0]


def test_mock_runs_are_free_and_not_counted_as_llm_calls(settings_override: Make) -> None:
    p = factory.build_providers(settings_override())
    hints = {"keywords": ["mfa"], "chunks": [{"chunk_id": "a:p001:c000", "text": "MFA is on."}]}
    result = p.llm.complete_json([], DraftFinding, purpose="mapper", hints=hints)
    assert result.parsed.status.value == "met" and result.cached is False
    s = p.tracker.summary()
    assert (s.llm_calls, s.cache_hits, s.tokens_in, s.tokens_out, s.usd) == (0, 0, 0, 0, 0.0)


@pytest.mark.parametrize("backend", ["sqlite", "jsonl"])
def test_close_is_safe_to_call_twice_and_for_every_backend(
    settings_override: Make, backend: str
) -> None:
    p = factory.build_providers(
        settings_override(llm={"provider": "ollama"}, cache={"backend": backend})
    )
    p.close()
    p.close()


def test_an_unknown_registry_name_is_a_clear_error(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(factory.LLM_PROVIDERS, "mock")
    with pytest.raises(
        ConfigError, match=r"LLM provider 'mock' is not implemented yet \(available: \["
    ):
        factory.build_providers(settings_override(llm={"provider": "mock"}))
