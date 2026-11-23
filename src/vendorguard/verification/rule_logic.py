"""The one definition of the rule decider's triage and verify logic.

Shared by ``providers/decide/rule.py`` and the mock LLM's judge so they can never disagree about
a label or a confidence. Pure functions: no model, no I/O, no randomness.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.finding import DraftStatus
from vendorguard.utils.keywords import matching_phrases
from vendorguard.verification.keyword_reading import read_status

# Confidence of a near miss (some keywords, not enough) or an embedding-only match.
UNSURE_CONFIDENCE = 0.5


@dataclass(frozen=True)
class Verdict:
    """A label, a confidence in [0, 1] and the keywords that were found."""

    label: DecisionLabel
    confidence: float
    hits: list[str]


def triage_verdict(
    texts: Sequence[str],
    keywords: Sequence[str],
    top_cosine: float,
    rules: RuleDeciderSettings,
) -> Verdict:
    """Addressed if enough keywords appear or the best raw cosine similarity passes its floor.

    A confident ``not_addressed`` (no keyword at all, weak retrieval) has confidence 1.0; a
    near miss (some keywords, not enough) only 0.5, so it is never skipped without a model call.
    Raw BM25 is unbounded and cannot be compared with a 0..1 floor (measured on the samples: a
    missing control still scores up to 20), so the floor applies to the raw cosine similarity and
    is inactive (0.0) without embeddings.
    """
    hits = matching_phrases(" ".join(texts), keywords)
    total = max(len(keywords), 1)
    needed = max(rules.triage_min_keyword_hits, 1)
    if len(hits) >= needed:
        confidence = min(1.0, UNSURE_CONFIDENCE + UNSURE_CONFIDENCE * len(hits) / total)
        return Verdict(DecisionLabel.ADDRESSED, round(confidence, 6), hits)
    if top_cosine >= rules.triage_min_retrieval_score:
        return Verdict(DecisionLabel.ADDRESSED, UNSURE_CONFIDENCE, hits)
    return Verdict(DecisionLabel.NOT_ADDRESSED, UNSURE_CONFIDENCE if hits else 1.0, hits)


def verify_verdict(
    status: DraftStatus,
    quotes: Sequence[str],
    keywords: Sequence[str],
    rules: RuleDeciderSettings,
) -> Verdict:
    """Supported if the WHOLE quoted text covers enough keywords and reads as ``status``.

    Reading uses ``read_status``: a negative signal means ``not_met``, a partial signal means
    ``partial``, otherwise ``met``. So ``met`` fails on any partial or negative signal and
    ``not_met`` needs a negative one. ``no_evidence`` is supported only without quotes. The rules
    are binary, so the confidence is 1.0 either way.
    """
    text = " ".join(quotes)
    hits = matching_phrases(text, keywords)
    if status is DraftStatus.NO_EVIDENCE:
        supported = not quotes
    else:
        coverage = len(hits) / max(len(keywords), 1)
        supported = (
            bool(quotes)
            and coverage >= rules.verify_min_keyword_coverage
            and read_status(text, rules) is status
        )
    label = DecisionLabel.SUPPORTED if supported else DecisionLabel.UNSUPPORTED
    return Verdict(label, 1.0, hits)


__all__ = ["UNSURE_CONFIDENCE", "Verdict", "triage_verdict", "verify_verdict"]
