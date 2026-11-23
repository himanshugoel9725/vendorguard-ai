"""JSONL cassette backend."""

import json
from pathlib import Path

import pytest

from vendorguard.errors import ConfigError
from vendorguard.providers.cache.jsonl_cache import JsonlCache


def test_put_get_and_miss(tmp_path: Path) -> None:
    cache = JsonlCache(tmp_path / "c")
    assert cache.get("k") is None
    cache.put("k", {"v": [1, 2]}, purpose="mapper")
    assert cache.get("k") == {"v": [1, 2]}


def test_one_file_per_purpose_with_one_line_per_put(tmp_path: Path) -> None:
    cache = JsonlCache(tmp_path / "c")
    cache.put("a", {"v": 1}, purpose="mapper")
    cache.put("b", {"v": 2}, purpose="mapper")
    cache.put("c", {"v": 3}, purpose="intake")
    assert sorted(p.name for p in (tmp_path / "c").iterdir()) == ["intake.jsonl", "mapper.jsonl"]
    lines = (tmp_path / "c" / "mapper.jsonl").read_text().splitlines()
    assert [json.loads(x)["key"] for x in lines] == ["a", "b"]


def test_a_new_instance_loads_what_was_recorded(tmp_path: Path) -> None:
    first = JsonlCache(tmp_path / "c")
    first.put("k", {"v": 1}, purpose="judge")
    assert JsonlCache(tmp_path / "c").get("k") == {"v": 1}


def test_save_sorts_by_key_and_keeps_the_last_write(tmp_path: Path) -> None:
    cache = JsonlCache(tmp_path / "c")
    for key in ("zz", "aa", "mm"):
        cache.put(key, {"v": key}, purpose="mapper")
    cache.put("aa", {"v": "newer"}, purpose="mapper")
    cache.save()
    rows = [json.loads(x) for x in (tmp_path / "c" / "mapper.jsonl").read_text().splitlines()]
    assert [r["key"] for r in rows] == ["aa", "mm", "zz"]
    assert rows[0]["value"] == {"v": "newer"}
    assert JsonlCache(tmp_path / "c").get("aa") == {"v": "newer"}


def test_the_saved_bytes_do_not_depend_on_the_recording_order(tmp_path: Path) -> None:
    items = [(f"k{n}", {"n": n, "f": n / 3}) for n in range(10)]
    for name, order in (("a", items), ("b", items[::-1])):
        cache = JsonlCache(tmp_path / name)
        for key, value in order:
            cache.put(key, value, purpose="mapper")
        cache.close()
    assert (tmp_path / "a" / "mapper.jsonl").read_bytes() == (
        tmp_path / "b" / "mapper.jsonl"
    ).read_bytes()


def test_files_are_ascii_with_one_json_object_per_line(tmp_path: Path) -> None:
    cache = JsonlCache(tmp_path / "c")
    cache.put("k", {"text": "café 中文"}, purpose="mapper")
    cache.close()
    raw = (tmp_path / "c" / "mapper.jsonl").read_bytes()
    assert raw.isascii() and raw.endswith(b"\n") and raw.count(b"\n") == 1
    assert JsonlCache(tmp_path / "c").get("k") == {"text": "café 中文"}


@pytest.mark.parametrize("purpose", ["../x", "a/b", "A", "", "1a", "x" * 40, "a b", "a.b"])
def test_unsafe_purposes_are_refused(tmp_path: Path, purpose: str) -> None:
    with pytest.raises(ValueError, match="unsafe cache purpose"):
        JsonlCache(tmp_path / "c").put("k", {}, purpose=purpose)
    assert not list((tmp_path / "c").glob("*")) if (tmp_path / "c").exists() else True


def test_a_missing_folder_is_an_empty_cache_and_nothing_is_created(tmp_path: Path) -> None:
    cache = JsonlCache(tmp_path / "nope")
    assert cache.get("k") is None
    cache.close()
    assert not (tmp_path / "nope").exists()


def test_blank_lines_are_ignored_and_corrupt_lines_are_loud(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "mapper.jsonl").write_text('\n{"key": "a", "value": {"v": 1}}\n\n')
    assert JsonlCache(folder).get("a") == {"v": 1}
    for bad in ("{broken", '{"key": "a"}', '{"key": "a", "value": 5}', "[1]"):
        (folder / "mapper.jsonl").write_text(bad + "\n")
        with pytest.raises(ConfigError, match=r"corrupt cassette mapper\.jsonl, line 1"):
            JsonlCache(folder)


def test_the_last_line_of_a_key_wins_when_loading(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "mapper.jsonl").write_text(
        '{"key": "a", "value": {"v": 1}}\n{"key": "a", "value": {"v": 2}}\n'
    )
    assert JsonlCache(folder).get("a") == {"v": 2}


def test_a_read_only_session_never_rewrites_the_cassettes(tmp_path: Path) -> None:
    """Even an unsorted, hand-edited cassette stays byte-for-byte as it was."""
    folder = tmp_path / "c"
    folder.mkdir()
    unsorted = '{"key": "zz", "value": {"v": 1}}\n{"key": "aa", "value": {"v": 2}}\n'
    (folder / "mapper.jsonl").write_text(unsorted)
    before = (folder / "mapper.jsonl").stat().st_mtime_ns
    cache = JsonlCache(folder)
    assert cache.get("aa") == {"v": 2}
    cache.save()
    cache.close()
    assert (folder / "mapper.jsonl").read_text() == unsorted
    assert (folder / "mapper.jsonl").stat().st_mtime_ns == before


def test_recording_after_loading_compacts_all_files(tmp_path: Path) -> None:
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "mapper.jsonl").write_text(
        '{"key": "zz", "value": {"v": 1}}\n{"key": "aa", "value": {"v": 2}}\n'
    )
    cache = JsonlCache(folder)
    cache.put("mm", {"v": 3}, purpose="mapper")
    cache.close()
    keys = [json.loads(x)["key"] for x in (folder / "mapper.jsonl").read_text().splitlines()]
    assert keys == ["aa", "mm", "zz"]
    cache.close()  # a second close has nothing to write
