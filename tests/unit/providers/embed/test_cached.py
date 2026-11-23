"""Cache wrapper: the second call is a hit, and only misses reach the wrapped embedder."""

from collections.abc import Sequence
from typing import Any

import pytest

from vendorguard.errors import EmbeddingError
from vendorguard.providers.embed.cached import PURPOSE, CachedEmbedder


class FakeEmbedder:
    """Deterministic vectors; remembers what it was asked."""

    def __init__(self, model: str = "m1") -> None:
        self.model = model
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [[float(len(t)), 0.5] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [float(len(text)), 9.0]


class DictCache:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self.purposes: list[str] = []

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        self.data[key] = value
        self.purposes.append(purpose)


@pytest.fixture
def parts() -> tuple[FakeEmbedder, DictCache, CachedEmbedder]:
    inner, cache = FakeEmbedder(), DictCache()
    return inner, cache, CachedEmbedder(inner, cache, "doc: ", "query: ")


def test_second_call_is_a_cache_hit(parts: tuple[FakeEmbedder, DictCache, CachedEmbedder]) -> None:
    inner, _cache, cached = parts
    first = cached.embed_documents(["alpha", "beta"])
    assert (cached.hits, cached.misses) == (0, 2)
    second = cached.embed_documents(["alpha", "beta"])
    assert second == first
    assert (cached.hits, cached.misses) == (2, 2)
    assert len(inner.document_calls) == 1


def test_only_missing_texts_reach_the_inner_embedder(
    parts: tuple[FakeEmbedder, DictCache, CachedEmbedder],
) -> None:
    inner, _cache, cached = parts
    cached.embed_documents(["alpha"])
    vectors = cached.embed_documents(["alpha", "gamma-long", "alpha"])
    assert inner.document_calls == [["alpha"], ["gamma-long"]]
    assert vectors == [[5.0, 0.5], [10.0, 0.5], [5.0, 0.5]]


def test_repeats_inside_one_call_are_embedded_once(
    parts: tuple[FakeEmbedder, DictCache, CachedEmbedder],
) -> None:
    inner, _cache, cached = parts
    assert cached.embed_documents(["x", "x", "x"]) == [[1.0, 0.5]] * 3
    assert inner.document_calls == [["x"]]
    assert cached.misses == 1


def test_queries_are_cached_too(parts: tuple[FakeEmbedder, DictCache, CachedEmbedder]) -> None:
    inner, _cache, cached = parts
    assert cached.embed_query("mfa") == cached.embed_query("mfa") == [3.0, 9.0]
    assert inner.query_calls == ["mfa"]
    assert (cached.hits, cached.misses) == (1, 1)


def test_documents_and_queries_do_not_share_entries(
    parts: tuple[FakeEmbedder, DictCache, CachedEmbedder],
) -> None:
    inner, _cache, cached = parts
    cached.embed_documents(["same"])
    cached.embed_query("same")
    assert inner.query_calls == ["same"]  # different prefix, different key


def test_key_depends_on_model_prefix_and_text_but_never_contains_the_text() -> None:
    a = CachedEmbedder(FakeEmbedder("m1"), DictCache(), "doc: ", "q: ")
    b = CachedEmbedder(FakeEmbedder("m2"), DictCache(), "doc: ", "q: ")
    keys = {a.key("doc: ", "t"), a.key("other: ", "t"), a.key("doc: ", "u"), b.key("doc: ", "t")}
    assert len(keys) == 4
    assert a.key("doc: ", "t") == a.key("doc: ", "t")
    assert "t" not in a.key("doc: ", "secret customer text")
    assert len(a.key("doc: ", "t")) == 64


def test_changing_the_prefix_does_not_reuse_old_vectors() -> None:
    inner, cache = FakeEmbedder(), DictCache()
    CachedEmbedder(inner, cache, "doc: ", "q: ").embed_documents(["t"])
    CachedEmbedder(inner, cache, "passage: ", "q: ").embed_documents(["t"])
    assert len(inner.document_calls) == 2 and len(cache.data) == 2


def test_entries_are_stored_with_the_embedding_purpose(
    parts: tuple[FakeEmbedder, DictCache, CachedEmbedder],
) -> None:
    _inner, cache, cached = parts
    cached.embed_documents(["a"])
    cached.embed_query("b")
    assert cache.purposes == [PURPOSE, PURPOSE] == ["embedding", "embedding"]
    assert all(set(v) == {"embedding"} for v in cache.data.values())


def test_a_damaged_cache_entry_is_recomputed(
    parts: tuple[FakeEmbedder, DictCache, CachedEmbedder],
) -> None:
    inner, cache, cached = parts
    cached.embed_documents(["a"])
    key = next(iter(cache.data))
    cache.data[key] = {"embedding": "broken"}
    assert cached.embed_documents(["a"]) == [[1.0, 0.5]]
    assert len(inner.document_calls) == 2
    cache.data[key] = {}
    assert cached.embed_documents(["a"]) == [[1.0, 0.5]]


def test_wrong_number_of_vectors_from_inner_is_an_error() -> None:
    class Broken(FakeEmbedder):
        def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            return []

    cached = CachedEmbedder(Broken(), DictCache(), "d: ", "q: ")
    with pytest.raises(EmbeddingError, match="wrong number"):
        cached.embed_documents(["a"])


def test_no_texts_means_no_lookups_and_no_inner_call(
    parts: tuple[FakeEmbedder, DictCache, CachedEmbedder],
) -> None:
    inner, _cache, cached = parts
    assert cached.embed_documents([]) == []
    assert inner.document_calls == [] and (cached.hits, cached.misses) == (0, 0)


def test_model_name_is_taken_from_the_wrapped_embedder() -> None:
    assert CachedEmbedder(FakeEmbedder("nomic"), DictCache(), "", "").model == "nomic"
