"""Phase 4 review fixes: cassettes are written atomically and safely from threads."""

import json
import os
import threading
from pathlib import Path

import pytest

from vendorguard.providers.cache.jsonl_cache import JsonlCache


def test_a_crash_while_compacting_never_truncates_a_committed_cassette(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "c"
    folder.mkdir()
    original = '{"key": "zz", "value": {"v": 1}}\n{"key": "aa", "value": {"v": 2}}\n'
    (folder / "mapper.jsonl").write_text(original)
    cache = JsonlCache(folder)
    cache.put("mm", {"v": 3}, purpose="mapper")
    appended = (folder / "mapper.jsonl").read_text()

    def crash(src: object, dst: object) -> None:
        raise OSError("simulated crash before the rename")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="simulated"):
        cache.save()
    # the file still holds every line it had (the original plus the appended one), none truncated
    assert (folder / "mapper.jsonl").read_text() == appended
    assert JsonlCache(folder).get("mm") == {"v": 3}


def test_no_temporary_files_are_left_behind(tmp_path: Path) -> None:
    cache = JsonlCache(tmp_path / "c")
    for n in range(5):
        cache.put(f"k{n}", {"n": n}, purpose="mapper" if n % 2 else "judge")
    cache.close()
    assert sorted(p.name for p in (tmp_path / "c").iterdir()) == ["judge.jsonl", "mapper.jsonl"]


def test_threads_can_record_and_read_at_the_same_time(tmp_path: Path) -> None:
    cache = JsonlCache(tmp_path / "c")
    errors: list[Exception] = []

    def work(n: int) -> None:
        try:
            for i in range(60):
                cache.put(f"k{n}-{i}", {"n": n, "i": i}, purpose="mapper")
                assert cache.get(f"k{n}-{i}") == {"n": n, "i": i}
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    cache.close()
    lines = (tmp_path / "c" / "mapper.jsonl").read_text().splitlines()
    assert len(lines) == 480 and len({json.loads(x)["key"] for x in lines}) == 480


def test_every_line_of_an_unsaved_cassette_is_complete_json(tmp_path: Path) -> None:
    """Appends from several threads never interleave inside a line."""
    cache = JsonlCache(tmp_path / "c")
    threads = [
        threading.Thread(
            target=lambda n=n: [
                cache.put(f"{n}-{i}", {"pad": "x" * 500}, purpose="mapper") for i in range(40)
            ]
        )
        for n in range(6)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    for line in (tmp_path / "c" / "mapper.jsonl").read_text().splitlines():
        assert json.loads(line)["value"] == {"pad": "x" * 500}
