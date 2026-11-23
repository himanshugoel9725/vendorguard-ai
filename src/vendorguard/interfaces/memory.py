"""Memory store and assistant interfaces (docs/PLAN.md section 6)."""

from typing import Protocol

from vendorguard.models.run import (
    Answer,
    AssessmentResult,
    AssessmentSummary,
    VendorSummary,
)


class MemoryStore(Protocol):
    """System of record for assessments, findings and analyst overrides."""

    def save_assessment(self, result: AssessmentResult) -> None:
        """Store (or replace) the result of one run."""
        ...

    def get_assessment(self, run_id: str) -> AssessmentResult | None:
        """The result of a run, or ``None`` if unknown."""
        ...

    def latest_assessment(
        self, vendor_id: str, *, exclude_run_id: str | None = None
    ) -> AssessmentResult | None:
        """The vendor's most recent result, optionally ignoring one run."""
        ...

    def list_assessments(self, vendor_id: str) -> list[AssessmentSummary]:
        """The vendor's history, newest first."""
        ...

    def list_vendors(self) -> list[VendorSummary]:
        """All known vendors."""
        ...


class MemoryAssistant(Protocol):
    """Answers questions about a vendor's history (a local LLM assistant or Letta)."""

    def ask(self, vendor_id: str, question: str) -> Answer:
        """An answer that cites run and control IDs."""
        ...


__all__ = ["MemoryAssistant", "MemoryStore"]
