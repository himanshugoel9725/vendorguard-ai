"""Findings: the LLM's draft for one control, and the final finding with its gate trace."""

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, field_validator

from vendorguard.models._base import ContractModel, NonEmptyStr, NonNegInt
from vendorguard.models.decision import GateTrace
from vendorguard.models.evidence import Citation, DraftCitation

# Schema bounds of the LLM output (see ADR-010): changing them needs a new prompt version.
MAX_CITATIONS = 3
MAX_RATIONALE_WORDS = 60


class DraftStatus(StrEnum):
    """Statuses the Mapper and Reviewer may return."""

    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"
    NO_EVIDENCE = "no_evidence"


class ControlStatus(StrEnum):
    """Final status of a control: the draft statuses plus ``needs_human_review``."""

    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"
    NO_EVIDENCE = "no_evidence"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


def _check_rationale(text: str) -> str:
    """Reject rationales longer than the contract allows."""
    if len(text.split()) > MAX_RATIONALE_WORDS:
        raise ValueError(f"rationale must be at most {MAX_RATIONALE_WORDS} words")
    return text


class DraftFinding(ContractModel):
    """LLM output schema for one control: status, verbatim quotes and a short rationale."""

    status: DraftStatus
    citations: Annotated[list[DraftCitation], Field(max_length=MAX_CITATIONS)]
    rationale: NonEmptyStr

    _rationale_length = field_validator("rationale")(_check_rationale)


class ExtractedEvidence(ContractModel):
    """LLM output schema of the Mapper and Reviewer (ADR-017): the quotes that bear on one
    control and a short rationale. The model does NOT choose the status; Python derives it."""

    citations: Annotated[list[DraftCitation], Field(max_length=MAX_CITATIONS)]
    rationale: NonEmptyStr
    _rationale_length = field_validator("rationale")(_check_rationale)


class Override(ContractModel):
    """An analyst's decision that replaces the system's status."""

    analyst: NonEmptyStr
    new_status: DraftStatus
    reason: NonEmptyStr
    at: AwareDatetime


class ControlFinding(ContractModel):
    """The final result for one control, with the gates that led to it."""

    control_id: NonEmptyStr
    status: ControlStatus
    citations: Annotated[list[Citation], Field(max_length=MAX_CITATIONS)]
    rationale: str
    trace: list[GateTrace]
    review_rounds: NonNegInt
    override: Override | None = None

    @property
    def effective_status(self) -> ControlStatus:
        """The status the rules engine uses: the analyst's override if there is one."""
        return ControlStatus(self.override.new_status.value) if self.override else self.status


__all__ = [
    "ControlFinding",
    "ControlStatus",
    "DraftFinding",
    "DraftStatus",
    "ExtractedEvidence",
    "Override",
]
