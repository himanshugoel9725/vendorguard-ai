"""Base class of the LLM agents: render a prompt, call the model, validate, audit.

An agent does one bounded job and never decides what happens next (that is the pipeline's job).
Concrete agents (Intake, Mapper, Reviewer, Reporter, Ask) only prepare the prompt variables and the
mock hints; this class does everything else and writes one audit event per call.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from vendorguard.errors import VendorGuardError
from vendorguard.interfaces.audit import AuditSink
from vendorguard.interfaces.llm import LLMClient
from vendorguard.models.llm import Usage
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.prompt_loader import PromptLoader

FAILED_SUFFIX = ".failed"


class BaseAgent[OutT: BaseModel]:
    """``name`` selects the prompt file; it is also the LLM ``purpose`` and the audit stage."""

    name: str
    output_model: type[OutT]

    def __init__(
        self, llm: LLMClient, prompts: PromptLoader, audit: AuditSink, cost: CostTracker
    ) -> None:
        self._llm = llm
        self._prompts = prompts
        self._audit = audit
        self._cost = cost

    def run(
        self,
        variables: Mapping[str, Any],
        *,
        hints: Mapping[str, Any] | None = None,
        control_id: str | None = None,
    ) -> OutT:
        """Render the prompt, ask the model, return the validated output.

        Exactly one audit event is written: on success with the hashes of the prompt and of the
        output, on failure (stage ``<name>.failed``) with the tokens already paid; then the error
        is re-raised. A missing prompt variable fails before any model call or event.
        """
        rendered = self._prompts.render(self.name, **variables)
        input_hash = hash_obj([m.model_dump() for m in rendered.messages])
        provider, model = self._llm.provider, self._llm.model
        try:
            result = self._llm.complete_json(
                rendered.messages, self.output_model, purpose=self.name, hints=hints
            )
        except VendorGuardError as exc:
            paid = Usage(
                tokens_in=exc.paid_usage[0] if exc.paid_usage else 0,
                tokens_out=exc.paid_usage[1] if exc.paid_usage else 0,
            )
            self._audit.record(
                stage=self.name + FAILED_SUFFIX,
                actor=f"{provider}/{model}",
                control_id=control_id,
                input_hash=input_hash,
                output_hash=hash_obj({"error": type(exc).__name__}),
                tokens_in=paid.tokens_in,
                tokens_out=paid.tokens_out,
                usd=self._usd(provider, model, paid),
                latency_ms=0.0,
                cached=False,
            )
            raise
        self._audit.record(
            stage=self.name,
            actor=f"{result.provider}/{result.model}",
            control_id=control_id,
            input_hash=input_hash,
            output_hash=hash_obj(result.parsed),
            tokens_in=result.usage.tokens_in,
            tokens_out=result.usage.tokens_out,
            usd=0.0 if result.cached else self._usd(result.provider, result.model, result.usage),
            latency_ms=result.latency_ms,
            cached=result.cached,
        )
        return result.parsed

    def _usd(self, provider: str, model: str, usage: Usage) -> float:
        return self._cost.cost_of(provider, model, usage)


__all__ = ["BaseAgent"]
