"""Phase 3 review fixes: damaged cache entries are misses, cache write errors are not fatal."""

import logging
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest
import respx

from vendorguard.config import Settings
from vendorguard.errors import EmbeddingError
from vendorguard.providers.embed.cached import CachedEmbedder
from vendorguard.providers.embed.ollama import OllamaEmbedder


class Inner:
    model = "m"

    def __init__(self) -> None:
        self.calls = 0

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(t)), 1.0] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return [float(len(text)), 2.0]


class DictCache:
    def __init__(self, fail_on_put: bool = False) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self.fail_on_put = fail_on_put

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        if self.fail_on_put:
            raise OSError("disk full")
        self.data[key] = value


@pytest.mark.parametrize(
    "damaged",
    [
        [],
        ["a", "b"],
        [True, False],
        [float("nan"), 1.0],
        [float("inf")],
        [None],
        "text",
        5,
        {"x": 1},
    ],
)
def test_a_damaged_cached_vector_is_recomputed_not_returned(damaged: object) -> None:
    inner, cache = Inner(), DictCache()
    cached = CachedEmbedder(inner, cache, "d: ", "q: ")
    cached.embed_documents(["abc"])
    key = next(iter(cache.data))
    cache.data[key] = {"embedding": damaged}
    assert cached.embed_documents(["abc"]) == [[3.0, 1.0]]
    assert inner.calls == 2
    assert cache.data[key] == {"embedding": [3.0, 1.0]}  # and the entry is repaired


def test_integer_vectors_from_a_json_cache_are_accepted() -> None:
    inner, cache = Inner(), DictCache()
    cached = CachedEmbedder(inner, cache, "d: ", "q: ")
    cached.embed_documents(["abc"])
    cache.data[next(iter(cache.data))] = {"embedding": [3, 1]}
    assert cached.embed_documents(["abc"]) == [[3, 1]] and inner.calls == 1


def test_a_failing_cache_write_does_not_lose_the_computed_vectors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    inner, cache = Inner(), DictCache(fail_on_put=True)
    cached = CachedEmbedder(inner, cache, "d: ", "q: ")
    with caplog.at_level(logging.WARNING):
        vectors = cached.embed_documents(["a", "bb", "ccc"])
    assert vectors == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]]
    assert cached.misses == 3 and inner.calls == 1
    assert any("could not cache" in r.message and "OSError" in r.message for r in caplog.records)
    assert "disk full" not in caplog.text and "ccc" not in caplog.text  # no text, no details


def test_a_failing_cache_write_does_not_break_queries(caplog: pytest.LogCaptureFixture) -> None:
    cached = CachedEmbedder(Inner(), DictCache(fail_on_put=True), "d: ", "q: ")
    with caplog.at_level(logging.WARNING):
        assert cached.embed_query("hello") == [5.0, 2.0]
    assert cached.misses == 1 and "could not cache" in caplog.text


@respx.mock
def test_an_integer_too_large_for_a_float_is_an_embedding_error(
    settings_override: Callable[..., Settings],
) -> None:
    s = settings_override(embeddings={"provider": "ollama"}).embeddings
    big = "1" + "0" * 400
    respx.post("http://localhost:11434/api/embed").mock(
        return_value=httpx.Response(200, content=f'{{"embeddings": [[{big}]]}}'.encode())
    )
    with pytest.raises(EmbeddingError, match="unusable"):
        OllamaEmbedder(s).embed_query("x")
