"""SHA-256 helpers; ``hash_obj`` hashes the canonical JSON so results match across processes."""

import hashlib
from typing import Any

from vendorguard.utils.jsonio import canonical_json


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Hex SHA-256 of UTF-8 text."""
    return sha256_bytes(text.encode("utf-8"))


def hash_obj(value: Any) -> str:
    """Hex SHA-256 of the canonical JSON of ``value``."""
    return sha256_text(canonical_json(value))


__all__ = ["hash_obj", "sha256_bytes", "sha256_text"]
