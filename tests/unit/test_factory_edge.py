"""Factory edge cases: full provider x backend x mode matrix, closers, isolation, error paths."""

from collections.abc import Callable
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from vendorguard import factory
from vendorguard.config import Settings
from vendorguard.errors import CacheMissError, ConfigError
from vendorguard.providers.embed.cached import CachedEmbedder
from vendorguard.providers.embed.ollama import OllamaEmbedder
from vendorguard.providers.llm.cached import CachedLLM
from vendorguard.providers.llm.ollama import OllamaLLM

Make = Callable[..., Settings]
KEYS = {
    n: {"api_key": "sk-fake-test-key"} for n in ("openai", "groq", "openai_compat")
}  # gitleaks:allow
LLMS = ["ollama", "openai", "groq", "openai_compat", "mock"]
BACKENDS = ["sqlite", "jsonl"]
MODES = ["off", "read_write", "read_only"]


@pytest.mark.parametrize(("llm", "backend", "mode"), list(product(LLMS, BACKENDS, MODES)))
def test_every_llm_backend_mode_combination_builds(
    settings_override: Make, llm: str, backend: str, mode: str
) -> None:
    s = settings_override(
        llm={"provider": llm, **KEYS},
        embeddings={"provider": "ollama"},
        cache={"backend": backend, "mode": mode},
    )
    p = factory.build_providers(s)
    try:
        assert isinstance(p.llm, CachedLLM) is (llm != "mock")
        assert isinstance(p.embedder, CachedEmbedder)
        assert p.cache is not None
    finally:
        p.close()


@pytest.mark.parametrize("llm", LLMS)
def test_disabled_cache_gives_no_cache_and_no_wrappers(settings_override: Make, llm: str) -> None:
    s = settings_override(
        llm={"provider": llm, **KEYS}, embeddings={"provider": "ollama"}, cache={"enabled": False}
    )
    p = factory.build_providers(s)
    assert p.cache is None
    assert not isinstance(p.llm, CachedLLM) and not isinstance(p.embedder, CachedEmbedder)
    assert factory.build_cache(s) is None
    p.close()


def test_closers_close_llm_embedder_then_cache(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vendorguard.providers.cache.sqlite_cache import SqliteCache

    calls: list[str] = []
    for cls, label in ((OllamaLLM, "llm"), (OllamaEmbedder, "embedder"), (SqliteCache, "cache")):
        real = cls.close

        def spy(self: Any, real: Callable[[Any], None] = real, label: str = label) -> None:
            calls.append(label)
            real(self)

        monkeypatch.setattr(cls, "close", spy)
    p = factory.build_providers(
        settings_override(
            llm={"provider": "ollama"},
            embeddings={"provider": "ollama"},
            cache={"backend": "sqlite"},
        )
    )
    assert len(p.closers) == 3
    p.close()
    assert calls == ["llm", "embedder", "cache"]


def test_mock_and_none_without_cache_have_nothing_to_close(settings_override: Make) -> None:
    p = factory.build_providers(settings_override(cache={"enabled": False}))
    assert p.closers == ()
    p.close()


def test_cache_storage_is_created_only_for_enabled_caches(
    settings_override: Make, tmp_path: Path
) -> None:
    off = settings_override(cache={"enabled": False})
    factory.build_providers(off).close()
    assert not off.cache.sqlite_path.exists() and not off.cache.jsonl_dir.exists()
    on = settings_override(cache={"backend": "sqlite"})
    factory.build_providers(on).close()
    assert on.cache.sqlite_path.exists()


def test_two_builds_have_independent_trackers(settings_override: Make) -> None:
    s = settings_override()
    a, b = factory.build_providers(s), factory.build_providers(s)
    assert a.tracker is not b.tracker
    a.close()
    b.close()


def test_cache_params_are_identical_for_the_same_settings(settings_override: Make) -> None:
    kw: dict[str, Any] = {"llm": {"provider": "openai", **KEYS}}
    assert factory.llm_cache_params(settings_override(**kw)) == factory.llm_cache_params(
        settings_override(**kw)
    )


def test_omit_params_are_sorted_in_cache_params(settings_override: Make) -> None:
    s = settings_override(
        llm={
            "provider": "groq",
            "groq": {
                "api_key": "sk-fake-test-key",
                "omit_params": ["top_p", "seed", "temperature"],
            },
        }  # gitleaks:allow
    )
    assert factory.llm_cache_params(s)["omit_params"] == ["seed", "temperature", "top_p"]


def test_local_providers_have_no_hosted_profile_params(settings_override: Make) -> None:
    params = factory.llm_cache_params(settings_override(llm={"provider": "ollama"}))
    assert not {"response_format", "max_tokens_field", "omit_params"} & set(params)


def test_ollama_embeddings_read_only_with_no_texts_needs_no_recording(
    settings_override: Make,
) -> None:
    p = factory.build_providers(
        settings_override(embeddings={"provider": "ollama"}, cache={"mode": "read_only"})
    )
    assert p.embedder.embed_documents([]) == []
    with pytest.raises(CacheMissError):
        p.embedder.embed_documents(["never recorded"])
    p.close()


def test_mock_llm_read_only_is_never_cached_so_never_misses(settings_override: Make) -> None:
    p = factory.build_providers(settings_override(cache={"mode": "read_only"}))
    assert not isinstance(p.llm, CachedLLM)
    p.close()


def test_a_failing_builder_propagates(
    settings_override: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_: Settings) -> Any:
        raise ConfigError("boom")

    monkeypatch.setitem(factory.EMBEDDERS, "none", boom)
    with pytest.raises(ConfigError, match="boom"):
        factory.build_providers(settings_override())
