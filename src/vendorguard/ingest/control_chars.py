"""Remove characters that are never document text: controls, surrogates and invisible overrides."""

import unicodedata

KEEP = frozenset({"\n", "\t", "\f", "­"})  # soft hyphens are handled by the cleaner
INVISIBLE = frozenset(
    {"​", "﻿", *map(chr, range(0x202A, 0x202F)), *map(chr, range(0x2066, 0x206A))}
)  # zero-width space, BOM, and the bidirectional embedding/override/isolate controls


def remove_control_characters(text: str) -> str:
    """Drop control characters (except newline, tab, form feed), lone surrogates and invisible
    bidirectional or zero-width characters, so later hashing and encoding can never fail on them."""
    return "".join(
        ch
        for ch in text
        if ch in KEEP or (ch not in INVISIBLE and unicodedata.category(ch) not in ("Cc", "Cs"))
    )


__all__ = ["remove_control_characters"]
