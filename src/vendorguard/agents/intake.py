"""Intake Agent: extracts the vendor profile from the first chunks of the documents."""

from collections.abc import Sequence

from vendorguard.agents.base import BaseAgent
from vendorguard.config_models.core import IntakeSettings
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.llm import LLMClient
from vendorguard.models.evidence import Chunk
from vendorguard.models.vendor import MAX_ITEMS, MAX_TEXT_CHARS, DataCategory, VendorProfile
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.utils.prompt_loader import PromptLoader


class IntakeAgent(BaseAgent[VendorProfile]):
    """One model call per run; the cover and first pages of a document usually hold the facts."""

    name = "intake"
    output_model = VendorProfile

    def __init__(
        self,
        llm: LLMClient,
        prompts: PromptLoader,
        audit: AuditSink,
        cost: CostTracker,
        settings: IntakeSettings,
    ) -> None:
        super().__init__(llm, prompts, audit, cost)
        self._max_chunks = settings.max_chunks

    def extract(self, chunks: Sequence[Chunk]) -> VendorProfile:
        """The profile read from the first ``intake.max_chunks`` chunks in document order."""
        selected = sorted(chunks, key=lambda c: c.chunk_id)[: self._max_chunks]
        variables = {
            "chunks": selected,
            "max_items": MAX_ITEMS,
            "max_chars": MAX_TEXT_CHARS,
            "categories": ", ".join(category.value for category in DataCategory),
        }
        return self.run(variables, hints={"text": " ".join(c.text for c in selected)})


__all__ = ["IntakeAgent"]
