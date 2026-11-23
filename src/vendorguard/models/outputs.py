"""LLM output schemas of the judge, reporter and ask agents (the other agents use ``DraftFinding``
and ``VendorProfile``). Bounds are part of the schema sent to the model (see ADR-010)."""

from typing import Annotated

from pydantic import Field

from vendorguard.models._base import ContractModel, NonEmptyStr, Probability
from vendorguard.models.decision import DecisionLabel

MAX_REASON_CHARS = 200
MAX_CITED_IDS = 30


class JudgeOutput(ContractModel):
    """The LLM judge's answer to one gate question: a label, a confidence and a short reason."""

    label: DecisionLabel
    confidence: Probability
    reason: Annotated[str, Field(max_length=MAX_REASON_CHARS)] = ""


class SummaryOutput(ContractModel):
    """The Reporter Agent's executive summary."""

    summary: NonEmptyStr


class AskOutput(ContractModel):
    """The Ask Agent's reply with the run and control IDs it relies on."""

    text: NonEmptyStr
    cited_run_ids: Annotated[list[str], Field(max_length=MAX_CITED_IDS)]
    cited_control_ids: Annotated[list[str], Field(max_length=MAX_CITED_IDS)]


__all__ = ["AskOutput", "JudgeOutput", "SummaryOutput"]
