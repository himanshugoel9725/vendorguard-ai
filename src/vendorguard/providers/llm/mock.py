"""The mock LLM: a deterministic keyword baseline that needs no model, key or network.

It answers by ``purpose`` from structured ``hints`` (JSON-like dicts that the agents pass only to
this provider) and ignores the chat messages. Hints per purpose:

* ``intake``:   ``{"text": str}`` (the text of the intake chunks)
* ``mapper``:   ``{"keywords": [str], "chunks": [{"chunk_id": str, "text": str}],``
  ``"max_quote_chars": int (optional)}``
* ``judge``:    triage ``{"task": "triage", "keywords": [str], "evidence": [str]}``; verify
  ``{"task": "verify", "keywords": [str], "status": str, "quotes": [str]}``
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
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.finding import DraftStatus
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.providers.llm import mock_reports
from vendorguard.providers.llm.mock_intake import extract_profile
from vendorguard.utils.keywords import matching_phrases
from vendorguard.verification.keyword_reading import first_sentence_with, read_status

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
                status = read_status(sentence, self._rules)
                quote = sentence[:limit].rstrip() if limit else sentence
                return {
                    "status": status.value,
                    "citations": [{"chunk_id": chunk["chunk_id"], "quote": quote}],
                    "rationale": f"Keyword baseline: the first matching sentence mentions "
                    f"{', '.join(hits[:3])} and reads as {status.value}.",
                }
        return {
            "status": DraftStatus.NO_EVIDENCE.value,
            "citations": [],
            "rationale": "No retrieved sentence mentions the control's keywords.",
        }

    def _judge(self, hints: Hints) -> dict[str, Any]:
        task, keywords = _need(hints, "task"), list(_need(hints, "keywords"))
        total = max(len(keywords), 1)
        if task == "triage":
            hits = matching_phrases(" ".join(_need(hints, "evidence")), keywords)
            needed = max(self._rules.triage_min_keyword_hits, 1)
            if len(hits) >= needed:
                return _verdict(
                    DecisionLabel.ADDRESSED, min(1.0, 0.5 + 0.5 * len(hits) / total), hits
                )
            return _verdict(DecisionLabel.NOT_ADDRESSED, 0.5 if hits else 1.0, hits)
        if task == "verify":
            return self._verify(
                DraftStatus(_need(hints, "status")), list(_need(hints, "quotes")), keywords
            )
        raise LLMError(f"the mock judge does not know the task '{task}'")

    def _verify(
        self, status: DraftStatus, quotes: list[str], keywords: list[str]
    ) -> dict[str, Any]:
        if status is DraftStatus.NO_EVIDENCE:
            supported = not quotes
            hits: list[str] = []
        else:
            first = first_sentence_with(quotes, keywords)
            hits = matching_phrases(" ".join(quotes), keywords)
            coverage = len(hits) / max(len(keywords), 1)
            supported = (
                first is not None
                and coverage >= self._rules.verify_min_keyword_coverage
                and read_status(first[0], self._rules) is status
            )
        label = DecisionLabel.SUPPORTED if supported else DecisionLabel.UNSUPPORTED
        return _verdict(label, 1.0, hits)


def _verdict(label: DecisionLabel, confidence: float, hits: list[str]) -> dict[str, Any]:
    return {
        "label": label.value,
        "confidence": round(confidence, 6),
        "reason": f"Keyword baseline: {len(hits)} keyword(s) matched.",
    }


__all__ = ["MockLLM"]
