"""The keyword baseline's way of reading evidence: sentences, signal phrases, statuses.

One definition shared by the sample generator's self-check, the mock LLM and (task 5.5) the rule
decider, so they can never disagree about what a sentence says.
"""

import re
from collections.abc import Iterable

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.finding import DraftStatus
from vendorguard.utils.keywords import matching_phrases

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences at ``.``, ``!`` or ``?`` followed by whitespace."""
    return [s for s in _SENTENCE_BREAK.split(text.strip()) if s]


def signals(text: str, rules: RuleDeciderSettings) -> tuple[list[str], list[str]]:
    """The (partial, negative) signal phrases found in ``text``."""
    return (
        matching_phrases(text, rules.partial_signal_phrases),
        matching_phrases(text, rules.negative_signal_phrases),
    )


def read_status(sentence: str, rules: RuleDeciderSettings) -> DraftStatus:
    """The status a keyword reader infers from a sentence that mentions a control.

    A negative signal wins over a partial one; no signal means ``met``.
    """
    partial, negative = signals(sentence, rules)
    if negative:
        return DraftStatus.NOT_MET
    return DraftStatus.PARTIAL if partial else DraftStatus.MET


def first_sentence_with(texts: Iterable[str], keywords: list[str]) -> tuple[str, list[str]] | None:
    """The first sentence (over the texts, in order) that contains a keyword, with its hits."""
    for text in texts:
        for sentence in split_sentences(text):
            hits = matching_phrases(sentence, keywords)
            if hits:
                return sentence, hits
    return None


__all__ = ["first_sentence_with", "read_status", "signals", "split_sentences"]
