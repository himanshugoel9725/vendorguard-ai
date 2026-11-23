"""Tokenizer shared by indexing and queries: lower-case alphanumeric tokens minus stop words."""

import re
from collections.abc import Iterable

_TOKEN = re.compile(r"[^\W_]+")


class Tokenizer:
    """Splits text into lower-case letter/digit runs and drops stop words."""

    def __init__(self, stop_words: Iterable[str]) -> None:
        self._stop_words = frozenset(word.lower() for word in stop_words)

    def tokenize(self, text: str) -> list[str]:
        """Tokens of ``text`` in order (``multi-factor`` gives ``multi`` and ``factor``)."""
        return [t for t in _TOKEN.findall(text.lower()) if t not in self._stop_words]


__all__ = ["Tokenizer"]
