"""All embedders share the Embedder shape; DictCache-like classes satisfy CacheBackend."""

import inspect
from collections.abc import Callable
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.interfaces.cache import CacheBackend
from vendorguard.interfaces.embedder import Embedder
from vendorguard.providers.embed.cached import CachedEmbedder
from vendorguard.providers.embed.null import NULL_MODEL, NullEmbedder
from vendorguard.providers.embed.ollama import OllamaEmbedder


class Store:
    def get(self, key: str) -> dict[str, Any] | None:
        return None

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        return None


@pytest.fixture
def embedders(settings_override: Callable[..., Settings]) -> list[Any]:
    cfg = settings_override(embeddings={"provider": "ollama"}).embeddings
    ollama = OllamaEmbedder(cfg)
    return [ollama, NullEmbedder(), CachedEmbedder(NullEmbedder(), Store(), "d", "q")]


def test_attributes_and_signatures(embedders: list[Any]) -> None:
    for emb in embedders:
        assert isinstance(emb.model, str) and emb.model
        docs = list(inspect.signature(emb.embed_documents).parameters)
        query = list(inspect.signature(emb.embed_query).parameters)
        assert docs == list(inspect.signature(Embedder.embed_documents).parameters)[1:]
        assert query == list(inspect.signature(Embedder.embed_query).parameters)[1:]


def test_null_and_cached_calls_return_lists(embedders: list[Any]) -> None:
    for emb in embedders[1:]:
        assert emb.embed_documents(["a", "b"]) == [[], []]
        assert emb.embed_query("a") == []


def test_cache_backend_shape() -> None:
    store: CacheBackend = Store()
    assert store.get("k") is None
    assert "purpose" in inspect.signature(CacheBackend.put).parameters
    assert inspect.signature(CacheBackend.put).parameters["purpose"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )
    assert inspect.signature(store.put).parameters.keys() == (
        inspect.signature(CacheBackend.put).parameters.keys() - {"self"}
    )


def test_null_embedder_model_and_determinism() -> None:
    null = NullEmbedder()
    assert null.model == NULL_MODEL == "none"
    out = null.embed_documents(["a"] * 1000)
    assert out == [[]] * 1000 and out == null.embed_documents(["a"] * 1000)
    assert null.embed_documents([]) == []
