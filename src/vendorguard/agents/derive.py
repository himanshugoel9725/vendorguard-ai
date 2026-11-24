"""Derive the status of a finding from the quotes the model extracted (ADR-017)."""

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.models.control import Control
from vendorguard.models.finding import DraftFinding, DraftStatus, ExtractedEvidence
from vendorguard.utils.keywords import matching_phrases
from vendorguard.verification.keyword_reading import read_status

NOT_ABOUT_CONTROL = "The quoted text does not mention this control."


def derive_finding(
    control: Control, extracted: ExtractedEvidence, rules: RuleDeciderSettings
) -> DraftFinding:
    """The model chooses WHAT to quote; the rules decide what the quotes mean.

    No quote, or quotes that contain none of the control's keywords, give ``no_evidence`` (and
    no citations: a no-evidence finding quotes nothing). Otherwise the whole quoted text is read
    with ``read_status``: a negative signal means ``not_met``, a partial signal ``partial``,
    else ``met``. Whether ``met`` is really backed by the quotes is the verify gate's job.
    """
    text = " ".join(c.quote for c in extracted.citations)
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


__all__ = ["NOT_ABOUT_CONTROL", "derive_finding"]
