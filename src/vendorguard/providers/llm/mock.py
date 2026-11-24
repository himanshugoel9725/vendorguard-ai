"""The mock LLM: a deterministic keyword baseline that needs no model, key or network.

It answers by ``purpose`` from structured ``hints`` (JSON-like dicts that the agents pass only to
this provider) and ignores the chat messages. Hints per purpose:

* ``intake``:   ``{"text": str}`` (the text of the intake chunks)
* ``mapper``:   ``{"keywords": [str], "chunks": [{"chunk_id": str, "text": str}],``
  ``"max_quote_chars": int (optional)}``; answers ``ExtractedEvidence`` (quotes + rationale, no
  status: the agent derives it, ADR-017)
* ``reviewer``: the same hints and answer as ``mapper`` (it ignores the draft and the flags)
* ``judge``:    triage ``{"task": "triage", "keywords": [str], "evidence": [str]}``; verify
  ``{"task": "verify", "keywords": [str], "status": str, "quotes": [str]}``; triage also takes an
  optional ``"top_score"`` (best raw BM25 score, default 0). Both use ``verification/rule_logic``
* ``reporter``: ``{"vendor_name", "overall", "band", "counts": {status: n}, "gaps": [control ids]}``
* ``ask``:      ``{"question": str, "runs": [{"run_id", "overall", "band",``
  ``"findings": {id: status}}]}`` (newest run first)

Usage is always zero, so the mock never costs anything and never counts against a budget.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from vendorguard.config_models.providers import RuleDeciderSettings
from vendorguard.errors import LLMError, SchemaValidationError
from vendorguard.models.finding import DraftStatus
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.providers.llm import mock_reports
from vendorguard.providers.llm.mock_intake import extract_profile
from vendorguard.verification.keyword_reading import first_sentence_with
from vendorguard.verification.rule_logic import triage_verdict, verify_verdict

T = TypeVar("T", bound=BaseModel)
Hints = Mapping[str, Any]


def _need(hints: Hints, key: str) -> Any:
    if key not in hints:
        raise LLMError(f"the mock LLM needs the hint '{key}' for this purpose")
    return hints[key]


class MockLLM:
    """Keyword-baseline answers for every agent purpose."""

    provider = "mock"
    model = "keyword-baseline"

    def __init__(self, rules: RuleDeciderSettings) -> None:
        self._rules = rules
        self._handlers: dict[str, Callable[[Hints], dict[str, Any]]] = {
            "intake": lambda h: extract_profile(str(_need(h, "text"))),
            "mapper": self._mapper,
            "reviewer": self._mapper,  # re-reads the (wider) evidence with the same keyword rules
            "judge": self._judge,
            "reporter": lambda h: {"summary": mock_reports.summary_text(dict(h))},
            "ask": lambda h: mock_reports.answer(str(_need(h, "question")), list(_need(h, "runs"))),
        }

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[T],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[T]:
        """Answer from ``hints`` and validate the answer as ``output_model``."""
        handler = self._handlers.get(purpose)
        if handler is None:
            raise LLMError(f"the mock LLM does not know the purpose '{purpose}'")
        try:
            data = handler(hints or {})
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise LLMError(
                f"the mock LLM got malformed hints for '{purpose}' ({type(exc).__name__})"
            ) from exc
        try:
            parsed = output_model.model_validate(data)
        except ValidationError as exc:
            raise SchemaValidationError(
                f"the mock answer for '{purpose}' does not fit {output_model.__name__}"
            ) from exc
        return LLMResult[T](parsed=parsed, usage=Usage(), provider=self.provider, model=self.model)

    def _mapper(self, hints: Hints) -> dict[str, Any]:
        keywords: list[str] = list(_need(hints, "keywords"))
        chunks = sorted(_need(hints, "chunks"), key=lambda c: c["chunk_id"])  # document order
        limit = hints.get("max_quote_chars")
        for chunk in chunks:
            found = first_sentence_with([chunk["text"]], keywords)
            if found:
                sentence, hits = found
                quote = sentence[:limit].rstrip() if limit else sentence
                return {
                    "citations": [{"chunk_id": chunk["chunk_id"], "quote": quote}],
                    "rationale": f"Keyword baseline: the first matching sentence mentions "
                    f"{', '.join(hits[:3])}.",
                }
        return {
            "citations": [],
            "rationale": "No retrieved sentence mentions the control's keywords.",
        }

    def _judge(self, hints: Hints) -> dict[str, Any]:
        task, keywords = _need(hints, "task"), list(_need(hints, "keywords"))
        if task == "triage":
            top = float(hints.get("top_score", 0.0))
            verdict = triage_verdict(list(_need(hints, "evidence")), keywords, top, self._rules)
        elif task == "verify":
            status = DraftStatus(_need(hints, "status"))
            verdict = verify_verdict(status, list(_need(hints, "quotes")), keywords, self._rules)
        else:
            raise LLMError(f"the mock judge does not know the task '{task}'")
        return {
            "label": verdict.label.value,
            "confidence": verdict.confidence,
            "reason": f"Keyword baseline: {len(verdict.hits)} keyword(s) matched.",
        }


__all__ = ["MockLLM"]
