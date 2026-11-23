"""SQLite cache backend: the local, read-write cache (``cache.backend = sqlite``)."""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from vendorguard.errors import ConfigError
from vendorguard.utils.jsonio import canonical_json

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    purpose TEXT NOT NULL,
    value TEXT NOT NULL
)
"""


class SqliteCache:
    """Key-value store in one SQLite file. Safe to share between threads (one lock)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise ConfigError(f"cannot open the cache database {path.name}: {exc}") from exc
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        """The stored value, or ``None`` on a miss (or an unreadable entry)."""
        with self._lock:
            row = self._conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row[0])
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def put(self, key: str, value: dict[str, Any], *, purpose: str) -> None:
        """Store ``value`` (canonical JSON) under ``key``, replacing any earlier entry."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, purpose, value) VALUES (?, ?, ?)",
                (key, purpose, canonical_json(value)),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the database."""
        with self._lock:
            self._conn.close()


__all__ = ["SqliteCache"]
