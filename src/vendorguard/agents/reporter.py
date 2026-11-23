"""Reporter Agent: the executive summary, guarded so it can only state facts from the result."""

import json
import logging
from collections.abc import Mapping
from typing import Any

from vendorguard.agents.base import BaseAgent
from vendorguard.config_models.core import ReportingSettings
from vendorguard.errors import LLMError, SchemaValidationError
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.llm import LLMClient
from vendorguard.models.outputs import SummaryOutput
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.reporting.fallback_summary import fallback_summary
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.verification.summary_guard import check_summary

log = logging.getLogger(__name__)
FALLBACK_STAGE = "reporter.fallback"


class ReporterAgent(BaseAgent[SummaryOutput]):
    """One model call per run. A model failure or a summary that fails the guard is replaced by
    the template (``reporting/fallback_summary``) and recorded as a ``reporter.fallback`` event."""

    name = "reporter"
    output_model = SummaryOutput

    def __init__(
        self,
        llm: LLMClient,
        prompts: PromptLoader,
        audit: AuditSink,
        cost: CostTracker,
        settings: ReportingSettings,
    ) -> None:
        super().__init__(llm, prompts, audit, cost)
        self._max_words = settings.summary_max_words

    def summarize(self, facts: Mapping[str, Any]) -> str:
        """The executive summary for ``facts`` (see ``reporting/facts.build_facts``)."""
        variables = {
            "max_words": self._max_words,
            "facts_json": json.dumps(facts, sort_keys=True, indent=2),
        }
        try:
            text = self.run(variables, hints=dict(facts)).summary
        except (LLMError, SchemaValidationError) as exc:  # already audited as reporter.failed
            return self._fallback(facts, [type(exc).__name__])
        problems = check_summary(text, facts, self._max_words)
        return self._fallback(facts, problems) if problems else text

    def _fallback(self, facts: Mapping[str, Any], problems: list[str]) -> str:
        log.warning("executive summary replaced by the template (%d problem(s))", len(problems))
        self._audit.record(
            stage=FALLBACK_STAGE,
            actor="python/fallback_summary",
            input_hash=hash_obj(dict(facts)),
            output_hash=hash_obj(problems),
            tokens_in=0,
            tokens_out=0,
            usd=0.0,
            latency_ms=0.0,
            cached=False,
        )
        return fallback_summary(facts)


__all__ = ["ReporterAgent"]
