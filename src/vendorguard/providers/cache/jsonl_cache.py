"""JSONL cache backend: committed test cassettes (``cache.backend = jsonl``).

One file per purpose (``<dir>/<purpose>.jsonl``). While recording, ``put`` appends a line; ``save``
rewrites every file sorted by key with one line per key, so committed cassettes diff cleanly.
"""

import json
import re
from pathlib import Path
from typing import Any

from vendorguard.errors import ConfigError
from vendorguard.utils.jsonio import canonical_json

_PURPOSE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class JsonlCache:
    """All entries of the folder are loaded into memory at start (the last line of a key wins)."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dirty = False  # becomes True once something is recorded
        self._entries: dict[str, tuple[str, dict[str, Any]]] = {}  # key -> (purpose, value)
        for path in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
            self._load(path)

    def get(self, key: str) -> dict[str, Any] | None:
        """The recorded value, or ``None`` on a miss."""
        entry = self._entries.get(key)
        return entry[1] if entry else None

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        """Record ``value``: remembered in memory and appended to ``<purpose>.jsonl``."""
        if not _PURPOSE.match(purpose):
            raise ValueError(f"unsafe cache purpose {purpose!r}")
        self._dir.mkdir(parents=True, exist_ok=True)
        with (self._dir / f"{purpose}.jsonl").open("a", encoding="ascii") as handle:
            handle.write(_line(key, value))
        self._entries[key] = (purpose, value)
        self._dirty = True

    def save(self) -> None:
        """Rewrite every purpose file sorted by key, one line per key (compaction).

        Does nothing unless something was recorded, so a replay never touches the cassettes.
        """
        if not self._dirty:
            return
        self._dirty = False
        by_purpose: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for key, (purpose, value) in self._entries.items():
            by_purpose.setdefault(purpose, []).append((key, value))
        self._dir.mkdir(parents=True, exist_ok=True)
        for purpose, items in sorted(by_purpose.items()):
            text = "".join(_line(k, v) for k, v in sorted(items))
            (self._dir / f"{purpose}.jsonl").write_text(text, encoding="ascii")

    def close(self) -> None:
        """Compact the files if anything was recorded."""
        self.save()

    def _load(self, path: Path) -> None:
        purpose = path.stem
        for number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
                self._entries[str(record["key"])] = (purpose, dict(record["value"]))
            except (ValueError, KeyError, TypeError) as exc:
                raise ConfigError(f"corrupt cassette {path.name}, line {number}") from exc


def _line(key: str, value: dict[str, Any]) -> str:
    return canonical_json({"key": key, "value": value}) + "\n"


__all__ = ["JsonlCache"]
