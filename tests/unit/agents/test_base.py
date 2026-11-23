"""BaseAgent: prompt -> model -> validated output, with exactly one audit event per call."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from vendorguard.agents.base import FAILED_SUFFIX, BaseAgent
from vendorguard.config import Settings
from vendorguard.errors import ConfigError, LLMError, SchemaValidationError
from vendorguard.models.audit import AuditEvent
from vendorguard.models.decision import Decision
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.utils.hashing import hash_obj
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow

PROMPT = """---
id: mapper
version: v1
output_model: Answer
---
## system
You are careful.
## user
Question: {{ question }}
"""


class Answer(BaseModel):
    text: str


class FakeLLM:
    """Records every call and answers with a canned result or raises."""

    def __init__(self, provider: str = "openai", model: str = "gpt-6-luna") -> None:
        self.provider, self.model = provider, model
        self.calls: list[dict[str, Any]] = []
        self.tokens = (100, 20)
        self.cached = False
        self.latency = 12.5
        self.error: Exception | None = None

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[Any],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[Any]:
        self.calls.append(
            {"messages": list(messages), "model": output_model, "purpose": purpose, "hints": hints}
        )
        if self.error:
            raise self.error
        return LLMResult(
            parsed=output_model(text="the answer"),
            usage=Usage(tokens_in=self.tokens[0], tokens_out=self.tokens[1]),
            provider=self.provider,
            model=self.model,
            cached=self.cached,
            latency_ms=self.latency,
        )


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, **fields: Any) -> AuditEvent:
        decision: Decision | None = fields.pop("decision", None)
        event = AuditEvent(
            run_id="run_test", seq=len(self.events), ts=utcnow(), decision=decision, **fields
        )
        self.events.append(event)
        return event


class MapperAgent(BaseAgent[Answer]):
    name = "mapper"
    output_model = Answer


@pytest.fixture
def parts(
    settings_override: Callable[..., Settings], tmp_path: Path
) -> Callable[..., tuple[MapperAgent, FakeLLM, FakeAudit, CostTracker]]:
    def build(llm: FakeLLM | None = None) -> tuple[MapperAgent, FakeLLM, FakeAudit, CostTracker]:
        (tmp_path / "mapper.v1.md").write_text(PROMPT, encoding="utf-8")
        s = settings_override()
        client, audit, tracker = llm or FakeLLM(), FakeAudit(), CostTracker(s.cost)
        agent = MapperAgent(client, PromptLoader(tmp_path, s.prompts), audit, tracker)
        return agent, client, audit, tracker

    return build


def test_run_returns_the_validated_output_and_asks_the_model_once(
    parts: Callable[..., tuple],
) -> None:  # type: ignore[type-arg]
    agent, llm, _audit, _tracker = parts()
    assert agent.run({"question": "Is MFA on?"}) == Answer(text="the answer")
    (call,) = llm.calls
    assert call["purpose"] == "mapper" and call["model"] is Answer and call["hints"] is None
    assert [m.role for m in call["messages"]] == ["system", "user"]
    assert call["messages"][1].content == "Question: Is MFA on?"


def test_hints_are_passed_through_to_the_model_untouched(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, _audit, _tracker = parts()
    hints = {"keywords": ["mfa"], "chunks": []}
    agent.run({"question": "q"}, hints=hints)
    assert llm.calls[0]["hints"] is hints


def test_one_audit_event_describes_the_call(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, audit, _tracker = parts()
    agent.run({"question": "q"}, control_id="IAM-02")
    (event,) = audit.events
    assert (event.stage, event.actor, event.control_id) == ("mapper", "openai/gpt-6-luna", "IAM-02")
    assert (event.tokens_in, event.tokens_out, event.cached, event.latency_ms) == (
        100,
        20,
        False,
        12.5,
    )
    assert event.input_hash == hash_obj([m.model_dump() for m in llm.calls[0]["messages"]])
    assert event.output_hash == hash_obj(Answer(text="the answer"))
    assert event.decision is None


def test_the_event_cost_comes_from_the_price_table(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, audit, tracker = parts()
    llm.tokens = (1_000_000, 500_000)  # gpt-6-luna: $0.10 in, $0.50 out per million tokens
    agent.run({"question": "q"})
    assert audit.events[0].usd == pytest.approx(0.35, abs=1e-9)
    assert audit.events[0].usd == tracker.cost_of(
        "openai", "gpt-6-luna", Usage(tokens_in=1_000_000, tokens_out=500_000)
    )


def test_a_cache_replay_is_recorded_as_cached_and_free(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, audit, _tracker = parts()
    llm.cached, llm.tokens, llm.latency = True, (0, 0), 0.0
    agent.run({"question": "q"})
    assert (audit.events[0].cached, audit.events[0].usd, audit.events[0].tokens_in) == (
        True,
        0.0,
        0,
    )


def test_a_cached_result_is_free_even_if_it_reports_tokens(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, audit, _tracker = parts()
    llm.cached = True
    agent.run({"question": "q"})
    assert audit.events[0].usd == 0.0


@pytest.mark.parametrize("provider", ["ollama", "mock"])
def test_free_providers_cost_nothing(parts: Callable[..., tuple], provider: str) -> None:  # type: ignore[type-arg]
    llm = FakeLLM(provider, "whatever")
    agent, _llm, audit, _tracker = parts(llm)
    agent.run({"question": "q"})
    assert audit.events[0].usd == 0.0 and audit.events[0].actor == f"{provider}/whatever"


def test_the_same_input_gives_the_same_hashes(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, _llm, audit, _tracker = parts()
    agent.run({"question": "same"})
    agent.run({"question": "same"})
    agent.run({"question": "different"})
    first, second, third = audit.events
    assert (first.input_hash, first.output_hash) == (second.input_hash, second.output_hash)
    assert third.input_hash != first.input_hash


def test_a_failed_call_writes_one_failed_event_and_re_raises(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, audit, _tracker = parts()
    llm.error = LLMError("boom")
    with pytest.raises(LLMError, match="boom"):
        agent.run({"question": "q"}, control_id="DAT-01")
    (event,) = audit.events
    assert event.stage == "mapper" + FAILED_SUFFIX and event.control_id == "DAT-01"
    assert (event.tokens_in, event.tokens_out, event.usd, event.cached) == (0, 0, 0.0, False)
    assert event.output_hash == hash_obj({"error": "LLMError"})


def test_a_failure_after_paid_attempts_records_what_was_spent(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, audit, _tracker = parts()
    error = SchemaValidationError("invalid after 2 attempts")
    error.paid_usage = (1_000_000, 500_000)
    llm.error = error
    with pytest.raises(SchemaValidationError):
        agent.run({"question": "q"})
    event = audit.events[0]
    assert (event.tokens_in, event.tokens_out) == (1_000_000, 500_000)
    assert event.usd == pytest.approx(0.35, abs=1e-9)
    assert event.output_hash == hash_obj({"error": "SchemaValidationError"})


def test_unexpected_errors_are_not_swallowed_or_audited(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, audit, _tracker = parts()
    llm.error = RuntimeError("bug")
    with pytest.raises(RuntimeError, match="bug"):
        agent.run({"question": "q"})
    assert audit.events == []


def test_a_missing_prompt_variable_fails_before_any_model_call_or_event(
    parts: Callable[..., tuple],
) -> None:  # type: ignore[type-arg]
    agent, llm, audit, _tracker = parts()
    with pytest.raises(ConfigError, match="'question' is undefined"):
        agent.run({})
    assert llm.calls == [] and audit.events == []


def test_every_call_writes_exactly_one_event(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, llm, audit, _tracker = parts()
    for n in range(5):
        agent.run({"question": f"q{n}"}, control_id=f"IAM-0{n}")
    assert len(audit.events) == len(llm.calls) == 5
    assert [e.control_id for e in audit.events] == [f"IAM-0{n}" for n in range(5)]


def test_the_prompt_text_never_reaches_the_audit_event(parts: Callable[..., tuple]) -> None:  # type: ignore[type-arg]
    agent, _llm, audit, _tracker = parts()
    agent.run({"question": "SECRET-DOC"})
    assert "SECRET-DOC" not in audit.events[0].model_dump_json()
