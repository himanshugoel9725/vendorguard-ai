"""Edge cases for CachedEmbedder: failures, key stability, ordering, sharing."""

import os
import random
import subprocess
import sys
from collections.abc import Sequence
from typing import Any

import pytest

from vendorguard.errors import EmbeddingError
from vendorguard.providers.embed.cached import CachedEmbedder


class Fake:
    def __init__(self, model: str = "m1", fail: bool = False) -> None:
        self.model = model
        self.fail = fail
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise EmbeddingError("down")
        self.calls.append(list(texts))
        return [[float(len(t)), 0.5] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        if self.fail:
            raise EmbeddingError("down")
        return [float(len(text)), 9.0]


class Store:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        self.data[key] = value


def _c(inner: Fake | None = None, store: Store | None = None, d: str = "d: ", q: str = "q: "):
    return CachedEmbedder(inner or Fake(), store or Store(), d, q)


def test_inner_failure_writes_nothing_and_counts_only_prior_hits() -> None:
    store = Store()
    c = _c(Fake(), store)
    c.embed_documents(["a"])
    assert (c.hits, c.misses, len(store.data)) == (0, 1, 1)
    bad = CachedEmbedder(Fake(fail=True), store, "d: ", "q: ")
    with pytest.raises(EmbeddingError):
        bad.embed_documents(["a", "b"])
    # the hit on "a" was counted before the failure; no miss counted; nothing new stored
    assert (bad.hits, bad.misses, len(store.data)) == (1, 0, 1)
    with pytest.raises(EmbeddingError):
        bad.embed_query("zzz")
    assert (bad.misses, len(store.data)) == (0, 1)


def test_key_properties() -> None:
    c = _c()
    k = c.key("d: ", "text")
    assert len(k) == 64 and int(k, 16) >= 0
    assert k == c.key("d: ", "text")
    assert k != _c(Fake("m2")).key("d: ", "text")
    assert k != c.key("D: ", "text")
    assert k != c.key("d: ", "texu")
    assert len(c.key("d: ", "é世🚀" * 100_000)) == 64
    assert c.key("d: ", "é世") != c.key("d: ", "e世")


def test_key_stable_across_processes_and_hashseed() -> None:
    code = (
        "from vendorguard.providers.embed.cached import CachedEmbedder as C\n"
        "class F:\n    model='m1'\n"
        "print(C(F(), None, 'd: ', 'q: ').key('d: ', 'héllo'))"
    )
    outs = set()
    for seed in ("0", "1", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        r = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        outs.add(r.stdout.strip())
    assert len(outs) == 1
    assert outs == {_c().key("d: ", "héllo")}


def test_cache_get_exception_propagates() -> None:
    class Broken(Store):
        def get(self, key: str) -> dict[str, Any] | None:
            raise RuntimeError("disk")

    with pytest.raises(RuntimeError, match="disk"):
        _c(store=Broken()).embed_documents(["a"])
    with pytest.raises(RuntimeError, match="disk"):
        _c(store=Broken()).embed_query("a")


def test_random_mixed_batch_keeps_order_and_dedups() -> None:
    rng = random.Random(1234)
    pool = [f"text-{i}-" + "x" * i for i in range(20)]
    inner, store = Fake(), Store()
    c = _c(inner, store)
    c.embed_documents(pool[:7])
    inner.calls.clear()
    texts = [rng.choice(pool) for _ in range(50)]
    out = c.embed_documents(texts)
    assert out == [[float(len(t)), 0.5] for t in texts]
    expected = list(dict.fromkeys(t for t in texts if t not in pool[:7]))
    assert inner.calls == [expected]


def test_query_and_document_share_entry_with_same_prefix() -> None:
    inner, store = Fake(), Store()
    c = _c(inner, store, d="p: ", q="p: ")
    c.embed_documents(["same"])
    assert c.key("p: ", "same") in store.data and len(store.data) == 1
    c.embed_query("same")
    assert (c.hits, c.misses) == (1, 1)


def test_different_prefixes_do_not_share() -> None:
    c = _c()
    c.embed_documents(["same"])
    c.embed_query("same")
    assert (c.hits, c.misses) == (0, 2)


def test_returned_vector_is_stored_list_value() -> None:
    store = Store()
    c = _c(store=store)
    c.embed_documents(["a"])
    vec = c.embed_documents(["a"])[0]
    assert vec is store.data[c.key("d: ", "a")]["embedding"]


def test_two_instances_share_one_cache() -> None:
    store = Store()
    first, second = Fake(), Fake()
    _c(first, store).embed_documents(["a"])
    c2 = _c(second, store)
    assert c2.embed_documents(["a"]) == [[1.0, 0.5]]
    assert (c2.hits, c2.misses, second.calls) == (1, 0, [])
