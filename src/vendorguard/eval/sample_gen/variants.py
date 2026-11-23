"""Deterministic choice among alternative phrasings (never Python's ``hash()``)."""

from vendorguard.utils.hashing import sha256_text

HEX_CHARS_USED = 16


def pick_index(base_id: str, key: str, state: str, count: int) -> int:
    """Index in ``range(count)`` derived from SHA-256 of (base vendor, key, state).

    The state is part of the key, so a control whose state is unchanged between two years keeps its
    wording, while a changed control draws from a different list.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    return int(sha256_text(f"{base_id}|{key}|{state}")[:HEX_CHARS_USED], 16) % count


__all__ = ["pick_index"]
