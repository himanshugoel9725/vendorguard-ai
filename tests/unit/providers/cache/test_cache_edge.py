"""Edge cases of the cache keys and of the SQLite and JSONL backends."""

import json
import sqlite3
import threading
from pathlib import Path

import pytest
from pydantic import BaseModel

from vendorguard.models.llm import ChatMessage
from vendorguard.providers.cache.jsonl_cache import JsonlCache
from vendorguard.providers.cache.keys import llm_key
from vendorguard.providers.cache.sqlite_cache import SqliteCache

SCHEMA = {"type": "object"}


def _key(**changes: object) -> str:
    base: dict[str, object] = dict(
        provider="p",
        model="m",
        purpose="mapper",
        messages=[ChatMessage(role="user", content="hi")],
        schema=SCHEMA,
        params={"temperature": 0.0},
    )
    return llm_key(**{**base, **changes})  # type: ignore[arg-type]


# --- keys ----------------------------------------------------------------------------------------


class _Hint(BaseModel):
    a: int
    b: list[str]


def test_pydantic_hint_equals_the_same_dict() -> None:
    as_model = {"x": _Hint(a=1, b=["u"]), "n": [{"k": (1, 2)}]}
    as_dict = {"x": {"a": 1, "b": ["u"]}, "n": [{"k": [1, 2]}]}
    assert _key(hints=as_model) == _key(hints=as_dict)


@pytest.mark.parametrize("bad", [object(), b"bytes"])
def test_non_json_values_raise_type_error(bad: object) -> None:
    with pytest.raises(TypeError):
        _key(params={"x": bad})
    with pytest.raises(TypeError):
        _key(hints={"x": bad})


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_floats_raise_value_error(bad: float) -> None:
    with pytest.raises(ValueError, match="NaN"):
        _key(params={"temperature": bad})
    with pytest.raises(ValueError, match="NaN"):
        _key(hints={"x": [bad]})


def test_float_params_round_to_six_decimals() -> None:
    assert _key(params={"t": 0.1 + 0.2}) == _key(params={"t": 0.3})
    assert _key(params={"t": 0.3}) != _key(params={"t": 0.31})


def test_unicode_and_very_long_messages() -> None:
    def msg(text: str) -> list[ChatMessage]:
        return [ChatMessage(role="user", content=text)]

    assert _key(messages=msg("Zürich ☃ \U0001f600")) == _key(messages=msg("Zürich ☃ \U0001f600"))
    assert _key(messages=msg("é")) != _key(messages=msg("é"))
    long = "x" * 2_000_000
    assert len(_key(messages=msg(long))) == 64
    assert _key(messages=msg(long)) != _key(messages=msg(long + "y"))


def test_empty_hints_equal_none() -> None:
    assert _key(hints={}) == _key(hints=None)


# --- sqlite --------------------------------------------------------------------------------------


def test_sqlite_unicode_nested_and_large_values(tmp_path: Path) -> None:
    cache = SqliteCache(tmp_path / "c.db")
    nested = {"a": {"b": [1, {"c": ["Zürich", "☃", "\U0001f600", 'q"\n\\']}]}, "n": None}
    cache.put("u", nested, purpose="mapper")
    big = {"blob": "é" * 1_000_000}
    cache.put("big", big, purpose="mapper")
    assert cache.get("u") == nested
    assert cache.get("big") == big
    cache.close()


def test_sqlite_many_keys_odd_keys_and_overwrite(tmp_path: Path) -> None:
    cache = SqliteCache(tmp_path / "c.db")
    for i in range(5000):
        cache.put(f"k{i}", {"i": i}, purpose="mapper")
    assert cache.get("k0") == {"i": 0} and cache.get("k4999") == {"i": 4999}
    assert cache.get("k5000") is None
    cache.put("", {"empty": True}, purpose="mapper")
    long_key = "k" * 10_000
    cache.put(long_key, {"long": True}, purpose="mapper")
    assert cache.get("") == {"empty": True} and cache.get(long_key) == {"long": True}
    cache.put("k1", {"i": "new"}, purpose="mapper")
    assert cache.get("k1") == {"i": "new"}
    cache.close()


def test_sqlite_second_instance_sees_committed_writes_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    first, second = SqliteCache(path), SqliteCache(path)
    first.put("a", {"v": 1}, purpose="mapper")
    assert second.get("a") == {"v": 1}
    first.close()
    second.put("b", {"v": 2}, purpose="mapper")
    second.close()
    third = SqliteCache(path)
    assert third.get("a") == {"v": 1} and third.get("b") == {"v": 2}
    third.close()


def test_sqlite_use_after_close_raises_programming_error(tmp_path: Path) -> None:
    cache = SqliteCache(tmp_path / "c.db")
    cache.close()
    with pytest.raises(sqlite3.ProgrammingError):
        cache.get("k")
    with pytest.raises(sqlite3.ProgrammingError):
        cache.put("k", {}, purpose="mapper")


def test_sqlite_two_instances_write_from_threads(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    caches = [SqliteCache(path), SqliteCache(path)]
    errors: list[BaseException] = []

    def work(index: int) -> None:
        try:
            for i in range(100):
                caches[index].put(f"t{index}-{i}", {"i": i}, purpose="mapper")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    check = SqliteCache(path)
    assert all(check.get(f"t{n}-{i}") == {"i": i} for n in range(2) for i in range(100))
    for c in [*caches, check]:
        c.close()


# --- jsonl ---------------------------------------------------------------------------------------


def test_jsonl_save_sorts_2000_entries_and_is_byte_stable(tmp_path: Path) -> None:
    cache = JsonlCache(tmp_path / "c")
    for i in reversed(range(2000)):
        cache.put(f"k{i:05d}", {"i": i}, purpose="mapper")
    cache.save()
    file = tmp_path / "c" / "mapper.jsonl"
    keys = [json.loads(x)["key"] for x in file.read_text().splitlines()]
    assert keys == sorted(keys) and len(keys) == 2000
    first = file.read_bytes()
    cache.put("k00001", {"i": 1}, purpose="mapper")  # dirty again, same content
    cache.save()
    cache.save()
    assert file.read_bytes() == first


def test_jsonl_two_instances_last_writer_wins_on_compaction(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    a, b = JsonlCache(folder), JsonlCache(folder)
    a.put("ka", {"v": "a"}, purpose="mapper")
    b.put("kb", {"v": "b"}, purpose="mapper")
    a.save()  # a only knows ka: rewrites the file without kb
    assert JsonlCache(folder).get("kb") is None
    b.save()  # b overwrites again without ka
    third = JsonlCache(folder)
    assert third.get("ka") is None and third.get("kb") == {"v": "b"}


def test_jsonl_disjoint_purposes_and_files_load_together(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    one, two = JsonlCache(folder), JsonlCache(folder)
    one.put("a", {"v": 1}, purpose="mapper")
    two.put("b", {"v": 2}, purpose="intake")
    one.save()
    two.save()
    assert sorted(p.name for p in folder.iterdir()) == ["intake.jsonl", "mapper.jsonl"]
    loaded = JsonlCache(folder)
    assert loaded.get("a") == {"v": 1} and loaded.get("b") == {"v": 2}


def test_jsonl_key_in_two_purpose_files_last_sorted_file_wins(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "alpha.jsonl").write_text('{"key":"k","value":{"v":"alpha"}}\n')
    (folder / "beta.jsonl").write_text('{"key":"k","value":{"v":"beta"}}\n')
    assert JsonlCache(folder).get("k") == {"v": "beta"}  # files load in sorted order


def test_jsonl_unicode_roundtrip_is_ascii_on_disk(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    cache = JsonlCache(folder)
    value = {"t": 'Zürich ☃ \U0001f600 "q" \\ \n\t'}
    cache.put("k", value, purpose="mapper")
    cache.save()
    assert (folder / "mapper.jsonl").read_bytes().isascii()
    assert JsonlCache(folder).get("k") == value


def test_jsonl_crlf_and_missing_trailing_newline_load(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "mapper.jsonl").write_bytes(
        b'{"key":"a","value":{"v":1}}\r\n\r\n{"key":"b","value":{"v":2}}'
    )
    cache = JsonlCache(folder)
    assert cache.get("a") == {"v": 1} and cache.get("b") == {"v": 2}


def test_jsonl_very_long_line(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    cache = JsonlCache(folder)
    value = {"text": "x" * 3_000_000}
    cache.put("k", value, purpose="mapper")
    assert JsonlCache(folder).get("k") == value
