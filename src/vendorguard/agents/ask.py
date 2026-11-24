"""Ask Agent (LocalAssistant): answers questions about a vendor's stored history, guarded."""

import json
import logging
from collections.abc import Sequence
from typing import Any

from vendorguard.agents.base import BaseAgent
from vendorguard.config_models.core import ReportingSettings
from vendorguard.config_models.providers import MemorySettings
from vendorguard.diff.reassessment import compute_diff
from vendorguard.errors import ConfigError, LLMError, SchemaValidationError
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.llm import LLMClient
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.models.outputs import AskOutput
from vendorguard.models.run import Answer, AssessmentResult
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.reporting.fallback_answer import fallback_answer
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.verification.answer_guard import check_answer

log = logging.getLogger(__name__)
FALLBACK_STAGE = "ask.fallback"
NO_RUNS = "No assessments are stored for this vendor."


def _run_data(results: Sequence[AssessmentResult]) -> list[dict[str, Any]]:
    """The facts the model may use, newest first. Statuses, scores and diffs only: no free text
    from vendor documents or analysts reaches the prompt."""
    data: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        item: dict[str, Any] = {
            "run_id": r.run_id,
            "created_at": r.created_at.isoformat(),
            "overall": r.score.overall,
            "band": r.score.band.value,
            "inherent_tier": r.inherent_risk.tier.value,
            "findings": {f.control_id: f.effective_status.value for f in r.findings},
        }
        if i + 1 < len(results):
            d = compute_diff(r.findings, r.score, results[i + 1])
            item["changes_since_previous_run"] = {
                "previous_run_id": d.previous_run_id,
                "new_gaps": d.new_gaps,
                "resolved_gaps": d.resolved_gaps,
                "score_delta": d.score_delta,
            }
        data.append(item)
    return data


class AskAgent(BaseAgent[AskOutput]):
    """Implements ``MemoryAssistant``. One model call per question; an answer that cites or names
    a run or control that is not in the data, and any model failure, is replaced by the template
    (``reporting/fallback_answer``) and recorded as an ``ask.fallback`` event."""

    name = "ask"
    output_model = AskOutput

    def __init__(
        self,
        llm: LLMClient,
        prompts: PromptLoader,
        audit: AuditSink,
        cost: CostTracker,
        memory: MemoryStore,
        settings: MemorySettings,
        reporting: ReportingSettings,
    ) -> None:
        super().__init__(llm, prompts, audit, cost)
        self._memory = memory
        self._history = settings.ask_max_history_runs
        self._max_chars = settings.ask_max_question_chars
        self._max_words = reporting.summary_max_words
        self._provider = f"local/{llm.provider}"

    def ask(self, vendor_id: str, question: str) -> Answer:
        """Answer ``question`` from the vendor's last ``memory.ask_max_history_runs`` results."""
        question = question.strip()
        if not question:
            raise ConfigError("the question must not be empty")
        if len(question) > self._max_chars:
            raise ConfigError(f"the question is longer than {self._max_chars} characters")
        results = [
            r
            for a in self._memory.list_assessments(vendor_id)[: self._history]
            if (r := self._memory.get_assessment(a.run_id)) is not None
        ]
        if not results:
            return self._answer(AskOutput(text=NO_RUNS, cited_run_ids=[], cited_control_ids=[]))
        data = _run_data(results)
        variables = {
            "max_words": self._max_words,
            "data_json": json.dumps(data, sort_keys=True, indent=2),
            "question": question,
        }
        hints = {
            "question": question,
            "runs": [{k: d[k] for k in ("run_id", "overall", "band", "findings")} for d in data],
        }
        run_ids = [d["run_id"] for d in data]
        control_ids = sorted({c for d in data for c in d["findings"]})
        try:
            out = self.run(variables, hints=hints)
        except (LLMError, SchemaValidationError) as exc:  # already audited as ask.failed
            return self._fallback(question, hints, [type(exc).__name__])
        problems = check_answer(out, run_ids, control_ids)
        return self._fallback(question, hints, problems) if problems else self._answer(out)

    def _answer(self, out: AskOutput) -> Answer:
        return Answer(
            text=out.text,
            cited_run_ids=sorted(set(out.cited_run_ids)),
            cited_control_ids=sorted(set(out.cited_control_ids)),
            provider=self._provider,
        )

    def _fallback(self, question: str, hints: dict[str, Any], problems: list[str]) -> Answer:
        log.warning("the answer was replaced by the template (%d problem(s))", len(problems))
        self._audit.record(
            stage=FALLBACK_STAGE,
            actor="python/fallback_answer",
            input_hash=hash_obj({"question": question, "runs": hints["runs"]}),
            output_hash=hash_obj(problems),
            tokens_in=0,
            tokens_out=0,
            usd=0.0,
            latency_ms=0.0,
            cached=False,
        )
        return self._answer(AskOutput.model_validate(fallback_answer(question, hints["runs"])))


__all__ = ["AskAgent"]
