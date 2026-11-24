"""One definition of a keyword or phrase match, shared by the sample generator, the mock LLM
and the rule decider: case-insensitive and whole-word (``backup`` does not match ``backups``)."""

import re
from collections.abc import Iterable
from functools import cache


@cache
def _pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)


def phrase_in(text: str, phrase: str) -> bool:
    """True if ``phrase`` occurs in ``text`` as a whole word or phrase, ignoring case."""
    return _pattern(phrase).search(text.replace("\u2019", "'")) is not None  # curly apostrophe


def matching_phrases(text: str, phrases: Iterable[str]) -> list[str]:
    """The phrases that occur in ``text``, in the order given."""
    return [phrase for phrase in phrases if phrase_in(text, phrase)]


__all__ = ["matching_phrases", "phrase_in"]
