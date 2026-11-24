"""Derive the status of a finding from the quotes the model extracted (ADR-017)."""

from collections.abc import Iterable

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.control import Control
from vendorguard.models.evidence import Chunk
from vendorguard.models.finding import DraftFinding, DraftStatus, ExtractedEvidence
from vendorguard.utils.keywords import matching_phrases
from vendorguard.verification.keyword_reading import read_status, split_sentences
from vendorguard.verification.text_normalize import normalize_text

NOT_ABOUT_CONTROL = "The quoted text does not mention this control."


def source_sentences(quote: str, chunks: Iterable[Chunk]) -> list[str]:
    """The whole source sentences that contain ``quote`` (or lie inside it), in chunk order.

    A model may quote only a clause ("encrypt all data at rest") of a sentence that says the
    opposite ("We do not encrypt all data at rest"): the status must be read from the full
    sentence. Returns ``[quote]`` when the quote is found in no sentence (a fuzzy quote).
    """
    needle = normalize_text(quote)
    found: list[str] = []
    for chunk in sorted(chunks, key=lambda c: c.chunk_id):
        for sentence in split_sentences(chunk.text):
            norm = normalize_text(sentence)
            if needle and (needle in norm or norm in needle) and sentence not in found:
                found.append(sentence)
    return found or [quote]


def derive_finding(
    control: Control,
    extracted: ExtractedEvidence,
    rules: RuleDeciderSettings,
    chunks: Iterable[Chunk] = (),
) -> DraftFinding:
    """The model chooses WHAT to quote; the rules decide what the quotes mean.

    No quote, or text containing none of the control's keywords, gives ``no_evidence`` (and no
    citations: a no-evidence finding quotes nothing). Otherwise the FULL SOURCE SENTENCES of the
    quotes (see ``source_sentences``; the quotes themselves when no chunks are given) are read
    with ``read_status``: a negative signal means ``not_met``, a partial signal ``partial``, else
    ``met``. Whether ``met`` is really backed by the quotes is the verify gate's job.
    """
    pool = list(chunks)
    texts: list[str] = []
    for citation in extracted.citations:
        texts.extend(source_sentences(citation.quote, pool))
    text = " ".join(texts)
    if not extracted.citations or not matching_phrases(text, control.keywords):
        return DraftFinding(
            status=DraftStatus.NO_EVIDENCE,
            citations=[],
            rationale=extracted.rationale if not extracted.citations else NOT_ABOUT_CONTROL,
        )
    return DraftFinding(
        status=read_status(text, rules),
        citations=extracted.citations,
        rationale=extracted.rationale,
    )


__all__ = ["NOT_ABOUT_CONTROL", "derive_finding", "source_sentences"]
