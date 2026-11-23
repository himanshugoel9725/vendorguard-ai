"""Text normalisation used to compare a quoted passage with its source text."""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)


def normalize_text(text: str) -> str:
    """NFKC, curly quotes and dashes to ASCII, case-folded, whitespace collapsed and stripped."""
    folded = unicodedata.normalize("NFKC", text).translate(_PUNCTUATION).casefold()
    return _WHITESPACE.sub(" ", folded).strip()


__all__ = ["normalize_text"]
