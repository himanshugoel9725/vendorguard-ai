"""SQLite cache backend."""

import sqlite3
import threading
from pathlib import Path

import pytest

from vendorguard.errors import ConfigError
from vendorguard.providers.cache.sqlite_cache import SqliteCache


@pytest.fixture
def cache(tmp_path: Path) -> SqliteCache:
    return SqliteCache(tmp_path / "state" / "cache.db")


def test_put_get_round_trip_and_miss(cache: SqliteCache) -> None:
    assert cache.get("k") is None
    cache.put("k", {"a": [1, 2.5, "x"], "b": {"c": None}}, purpose="mapper")
    assert cache.get("k") == {"a": [1, 2.5, "x"], "b": {"c": None}}
    assert cache.get("other") is None


def test_the_parent_folder_is_created_and_wal_is_on(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "er" / "cache.db"
    SqliteCache(path).close()
    assert path.exists()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_a_second_put_replaces_the_first(cache: SqliteCache) -> None:
    cache.put("k", {"v": 1}, purpose="mapper")
    cache.put("k", {"v": 2}, purpose="mapper")
    assert cache.get("k") == {"v": 2}


def test_entries_survive_closing_and_reopening(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    first = SqliteCache(path)
    first.put("k", {"v": 1}, purpose="embedding")
    first.close()
    assert SqliteCache(path).get("k") == {"v": 1}


def test_the_purpose_is_stored(cache: SqliteCache, tmp_path: Path) -> None:
    cache.put("k1", {"v": 1}, purpose="mapper")
    cache.put("k2", {"v": 2}, purpose="embedding")
    with sqlite3.connect(tmp_path / "state" / "cache.db") as db:
        rows = dict(db.execute("SELECT key, purpose FROM cache").fetchall())
    assert rows == {"k1": "mapper", "k2": "embedding"}


def test_values_are_stored_as_canonical_json(cache: SqliteCache, tmp_path: Path) -> None:
    cache.put("k", {"b": 0.1 + 0.2, "a": 1}, purpose="x")
    with sqlite3.connect(tmp_path / "state" / "cache.db") as db:
        assert db.execute("SELECT value FROM cache").fetchone()[0] == '{"a":1,"b":0.3}'


def test_hostile_keys_and_purposes_are_just_data(cache: SqliteCache, tmp_path: Path) -> None:
    key = "x'); DROP TABLE cache; --"
    cache.put(key, {"v": 1}, purpose="'; DELETE FROM cache; --")
    assert cache.get(key) == {"v": 1}
    cache.put("other", {"v": 2}, purpose="p")
    assert cache.get("other") == {"v": 2}


def test_an_unreadable_entry_counts_as_a_miss(cache: SqliteCache, tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "state" / "cache.db") as db:
        db.execute("INSERT INTO cache VALUES ('bad', 'x', '{not json')")
        db.execute("INSERT INTO cache VALUES ('list', 'x', '[1, 2]')")
    assert cache.get("bad") is None and cache.get("list") is None


def test_threads_can_share_one_cache(cache: SqliteCache) -> None:
    errors: list[Exception] = []

    def work(n: int) -> None:
        try:
            for i in range(25):
                cache.put(f"k{n}-{i}", {"n": n, "i": i}, purpose="mapper")
                assert cache.get(f"k{n}-{i}") == {"n": n, "i": i}
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and cache.get("k5-24") == {"n": 5, "i": 24}


def test_a_file_that_is_not_a_database_is_a_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_text("this is not sqlite" * 50)
    with pytest.raises(ConfigError, match=r"bad\.db"):
        SqliteCache(bad)
