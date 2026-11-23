"""CachedEmbedder cache modes: off bypasses, read_only replays and counts, read_write repairs."""

from collections.abc import Sequence
from typing import Any

import pytest

from vendorguard.errors import CacheMissError
from vendorguard.providers.embed.cached import CachedEmbedder


class Inner:
    model = "m"

    def __init__(self) -> None:
        self.doc_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.doc_calls.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [float(len(text)), 2.0]


class SpyCache:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self.gets: list[str] = []
        self.puts: list[str] = []

    def get(self, key: str) -> dict[str, Any] | None:
        self.gets.append(key)
        return self.data.get(key)

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        self.puts.append(key)
        self.data[key] = value


def build(mode: Any) -> tuple[Inner, SpyCache, CachedEmbedder]:
    inner, cache = Inner(), SpyCache()
    return inner, cache, CachedEmbedder(inner, cache, "d: ", "q: ", mode=mode)


def test_off_bypasses_the_cache_entirely() -> None:
    inner, cache, emb = build("off")
    assert emb.embed_documents(["a", "bb"]) == [[1.0, 1.0], [2.0, 1.0]]
    assert emb.embed_documents(["a", "bb"]) == [[1.0, 1.0], [2.0, 1.0]]
    assert emb.embed_query("abc") == [3.0, 2.0]
    assert cache.gets == [] and cache.puts == []
    assert len(inner.doc_calls) == 2 and inner.query_calls == ["abc"]
    assert (emb.hits, emb.misses) == (0, 0)


def test_off_passes_texts_unchanged_including_duplicates_and_empty() -> None:
    inner, _, emb = build("off")
    assert emb.embed_documents([]) == []
    emb.embed_documents(["x", "x"])
    assert inner.doc_calls == [[], ["x", "x"]]


def test_read_only_with_a_partly_recorded_batch_names_the_missing_count() -> None:
    inner, cache, rw = build("read_write")
    rw.embed_documents(["a", "b"])
    ro = CachedEmbedder(inner, cache, "d: ", "q: ", mode="read_only")
    inner.doc_calls.clear()
    puts = len(cache.puts)
    with pytest.raises(CacheMissError, match=r"^2 text\(s\)"):
        ro.embed_documents(["a", "c", "d", "b"])
    assert inner.doc_calls == [] and len(cache.puts) == puts
    assert (ro.hits, ro.misses) == (2, 2)


def test_read_only_missing_duplicates_count_once() -> None:
    _, _, ro = build("read_only")
    with pytest.raises(CacheMissError, match=r"^1 text\(s\)"):
        ro.embed_documents(["z", "z", "z"])
    assert ro.misses == 1


def test_read_only_replays_recorded_documents_and_queries() -> None:
    inner, cache, rw = build("read_write")
    docs = rw.embed_documents(["a", "bb"])
    query = rw.embed_query("hello")
    ro = CachedEmbedder(inner, cache, "d: ", "q: ", mode="read_only")
    inner.doc_calls.clear()
    inner.query_calls.clear()
    assert ro.embed_documents(["bb", "a"]) == [docs[1], docs[0]]
    assert ro.embed_query("hello") == query
    assert (ro.hits, ro.misses) == (3, 0)
    assert inner.doc_calls == [] and inner.query_calls == []


def test_read_only_query_miss_raises_and_counts() -> None:
    inner, cache, ro = build("read_only")
    with pytest.raises(CacheMissError, match="query"):
        ro.embed_query("nope")
    assert ro.misses == 1 and ro.hits == 0
    assert inner.query_calls == [] and cache.puts == []


def test_read_only_with_no_texts_works_without_a_recorded_entry() -> None:
    inner, _, ro = build("read_only")
    assert ro.embed_documents([]) == []
    assert inner.doc_calls == []


@pytest.mark.parametrize("damaged", [{"embedding": [1.0, float("nan")]}, {"embedding": []}, {}])
def test_read_write_repairs_a_damaged_entry(damaged: dict[str, Any]) -> None:
    inner, cache, emb = build("read_write")
    key = emb.key("d: ", "abc")
    cache.data[key] = damaged
    assert emb.embed_documents(["abc"]) == [[3.0, 1.0]]
    assert cache.data[key] == {"embedding": [3.0, 1.0]}
    assert emb.embed_documents(["abc"]) == [[3.0, 1.0]]
    assert len(inner.doc_calls) == 1


def test_read_only_treats_a_damaged_entry_as_a_miss() -> None:
    _, cache, ro = build("read_only")
    cache.data[ro.key("d: ", "abc")] = {"embedding": ["x"]}
    with pytest.raises(CacheMissError):
        ro.embed_documents(["abc"])
