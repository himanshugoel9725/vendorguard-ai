"""Seeded property tests of the cache keys and backends."""

import random
import string
from pathlib import Path

from vendorguard.models.llm import ChatMessage
from vendorguard.providers.cache.jsonl_cache import JsonlCache
from vendorguard.providers.cache.keys import embedding_key, llm_key
from vendorguard.providers.cache.sqlite_cache import SqliteCache


def _text(rng: random.Random) -> str:
    alphabet = string.ascii_letters + " \né☃"
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))


def test_10000_distinct_inputs_give_10000_distinct_keys() -> None:
    rng = random.Random(1234)
    seen_inputs: set[tuple[str, str, float]] = set()
    keys: set[str] = set()
    while len(seen_inputs) < 10_000:
        item = (_text(rng), rng.choice(["a", "b", "c"]), rng.randint(0, 10**6) / 1000)
        if item in seen_inputs:
            continue
        seen_inputs.add(item)
        text, model, temperature = item
        keys.add(
            llm_key(
                provider="p",
                model=model,
                purpose="mapper",
                messages=[ChatMessage(role="user", content=text)],
                schema={},
                params={"temperature": temperature},
            )
        )
    assert len(keys) == 10_000


def test_embedding_keys_are_distinct_and_deterministic() -> None:
    rng = random.Random(7)
    texts = {_text(rng) + str(i) for i in range(2000)}
    keys = {embedding_key("m", "query: ", t) for t in texts}
    assert len(keys) == len(texts)
    assert keys == {embedding_key("m", "query: ", t) for t in texts}


def test_sqlite_and_jsonl_agree_on_random_values(tmp_path: Path) -> None:
    rng = random.Random(99)
    entries = {
        f"key{i}": {"t": _text(rng), "n": rng.randint(-5, 5), "f": rng.randint(0, 99) / 8}
        for i in range(300)
    }
    sqlite = SqliteCache(tmp_path / "c.db")
    jsonl = JsonlCache(tmp_path / "cassettes")
    for key, value in entries.items():
        sqlite.put(key, value, purpose="mapper")
        jsonl.put(key, value, purpose="mapper")
    jsonl.save()
    reloaded = JsonlCache(tmp_path / "cassettes")
    for key, value in entries.items():
        assert sqlite.get(key) == value == jsonl.get(key) == reloaded.get(key)
    sqlite.close()


def test_jsonl_files_do_not_depend_on_insertion_order(tmp_path: Path) -> None:
    rng = random.Random(5)
    items = [(f"k{i}", {"v": i}) for i in range(200)]
    shuffled = items[:]
    rng.shuffle(shuffled)
    for folder, order in (("a", items), ("b", shuffled)):
        cache = JsonlCache(tmp_path / folder)
        for key, value in order:
            cache.put(key, value, purpose="mapper")
        cache.save()
    assert (tmp_path / "a" / "mapper.jsonl").read_bytes() == (
        tmp_path / "b" / "mapper.jsonl"
    ).read_bytes()
