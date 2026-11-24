"""Edge cases for the deciders: Jev client transport, Jev cap/budget, fallback, judge, mock."""

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from vendorguard import factory
from vendorguard.config import Settings
from vendorguard.errors import (
    BudgetExceededError,
    ConfigError,
    DeciderError,
    LLMError,
    SchemaValidationError,
)
from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import Control
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.evidence import Chunk, DraftCitation, ScoredChunk
from vendorguard.models.finding import DraftFinding, DraftStatus
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.decide.fallback import FallbackDecider
from vendorguard.providers.decide.jev import JevDecider
from vendorguard.providers.decide.jev_client import JevClient
from vendorguard.providers.decide.llm_judge import LlmJudgeDecider
from vendorguard.providers.decide.mock import MockDecider
from vendorguard.providers.decide.rule import RuleDecider
from vendorguard.providers.llm.mock import MockLLM
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow

ROOT = Path(__file__).resolve().parents[4]
URL = "https://openrouter.ai/api/alpha/decisions"
KEY = "fake-fake-fake-fake"
CONTROL = Control(
    id="IAM-02", title="MFA", domain="IAM", criticality="critical", iso27001=["8.5"],
    nist_csf=["PR.AA"], requirement="MFA is enforced.", met_criteria="MFA for all access.",
    keywords=["MFA", "2FA"],
)  # fmt: skip


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, **fields: Any) -> AuditEvent:
        e = AuditEvent(run_id="r", seq=len(self.events), ts=utcnow(), decision=None, **fields)
        self.events.append(e)
        return e


def _chunk(cid: str, text: str, raw: float | None = None) -> ScoredChunk:
    c = Chunk(chunk_id=cid, doc_id="d", page=1, text=text, char_start=0, char_end=len(text))
    return ScoredChunk(chunk=c, score=1.0, bm25=1.0, vector_raw=raw)


def _draft(status: DraftStatus = DraftStatus.MET, *quotes: str) -> DraftFinding:
    return DraftFinding(
        status=status,
        citations=[DraftCitation(chunk_id="d:p001:c000", quote=q) for q in quotes],
        rationale="r",
    )


def _answer(p: float, key: str = "supported") -> dict[str, Any]:
    return {
        "answers": {key: {"type": "noul", "noul": p}},
        "usage": {"input_tokens": 10, "output_tokens": 1},
    }


@pytest.fixture
def settings(settings_override: Any) -> Settings:
    s: Settings = settings_override(
        decision={"jev": {"api_key": KEY, "max_calls_per_run": 3}},
        llm={"retry_backoff_s": 0.0, "max_retries": 2},
    )
    return s


def _client(s: Settings) -> JevClient:
    return JevClient(s.decision.jev, s.llm)


def _jev(s: Settings) -> tuple[JevDecider, FakeAudit, CostTracker]:
    audit, cost = FakeAudit(), CostTracker(s.cost)
    return JevDecider(_client(s), s.decision.jev, audit, cost), audit, cost


# --- Jev client ----------------------------------------------------------------------------------


@respx.mock
@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_client_rejects_probability_outside_zero_one(settings: Settings, bad: float) -> None:
    respx.post(URL).respond(200, json=_answer(bad))
    with pytest.raises(DeciderError, match="outside 0..1"):
        _client(settings).ask({}, {"supported": {}})


@respx.mock
@pytest.mark.parametrize("p", [0.0, 1.0])
def test_client_accepts_the_probability_bounds(settings: Settings, p: float) -> None:
    respx.post(URL).respond(200, json=_answer(p))
    out, usage = _client(settings).ask({}, {"supported": {}})
    assert out == {"supported": p} and usage.tokens_in == 10


@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {"answers": {}, "usage": {"input_tokens": 1, "output_tokens": 1}},
        {"answers": {"supported": {"type": "noul", "noul": 0.5}}},
        {"answers": {"supported": {"type": "noul", "noul": "high"}}, "usage": {}},
        {"answers": {"supported": {"type": "noul"}}, "usage": {}},
        ["not", "a", "dict"],
    ],
)
def test_client_malformed_replies_are_decider_errors(settings: Settings, payload: Any) -> None:
    respx.post(URL).respond(200, json=payload)
    with pytest.raises(DeciderError):
        _client(settings).ask({}, {"supported": {}})


@respx.mock
def test_client_retries_5xx_then_succeeds(settings: Settings) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=_answer(0.7))]
    )
    out, _ = _client(settings).ask({}, {"supported": {}})
    assert out["supported"] == 0.7 and route.call_count == 2


@respx.mock
def test_client_retries_429_and_gives_up_after_max_retries(settings: Settings) -> None:
    route = respx.post(URL).respond(429, headers={"retry-after": "0"})
    with pytest.raises(DeciderError):
        _client(settings).ask({}, {"supported": {}})
    assert route.call_count == settings.llm.max_retries + 1


@respx.mock
def test_client_connect_error_is_a_decider_error(settings: Settings) -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(DeciderError):
        _client(settings).ask({}, {"supported": {}})


@respx.mock
def test_client_error_text_never_contains_the_key(settings: Settings) -> None:
    respx.post(URL).respond(400, json={"error": {"message": f"bad key {KEY}"}})
    with pytest.raises(DeciderError) as info:
        _client(settings).ask({}, {"supported": {}})
    assert KEY not in str(info.value)


@respx.mock
def test_client_sends_bearer_key_and_model_and_is_deterministic(settings: Settings) -> None:
    route = respx.post(URL).respond(200, json=_answer(0.5))
    c = _client(settings)
    state = {"b": 1, "a": [1, 2]}
    assert c.ask(state, {"supported": {}}) == c.ask(state, {"supported": {}})
    req = route.calls[0].request
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.content == route.calls[1].request.content


def test_client_allows_http_on_loopback_only(settings_override: Any) -> None:
    ok = settings_override(
        decision={"jev": {"api_key": KEY, "base_url": "http://127.0.0.1:9/alpha"}}
    )
    assert JevClient(ok.decision.jev, ok.llm).model == ok.decision.jev.model
    bad = settings_override(decision={"jev": {"api_key": KEY, "base_url": "http://example.com/a"}})
    with pytest.raises(ConfigError, match="https"):
        JevClient(bad.decision.jev, bad.llm)


def test_client_close_closes_the_injected_http_client(settings: Settings) -> None:
    http = httpx.Client()
    JevClient(settings.decision.jev, settings.llm, client=http).close()
    assert http.is_closed


# --- Jev decider ---------------------------------------------------------------------------------


@respx.mock
def test_jev_probability_exactly_half_is_yes(settings: Settings) -> None:
    respx.post(URL).respond(200, json=_answer(0.5, "addressed"))
    d = _jev(settings)[0].triage(CONTROL, [_chunk("d:p001:c000", "x")])
    assert d.label is DecisionLabel.ADDRESSED and d.confidence == 0.5


@respx.mock
def test_jev_cap_counts_failed_calls_and_stops_http(settings: Settings) -> None:
    route = respx.post(URL).respond(400, json={"error": {"message": "x"}})
    jev, audit, _ = _jev(settings)
    for _ in range(3):
        with pytest.raises(DeciderError, match="HTTP 400"):
            jev.verify(CONTROL, _draft(DraftStatus.MET, "MFA."), [])
    with pytest.raises(DeciderError, match="max_calls_per_run"):
        jev.verify(CONTROL, _draft(DraftStatus.MET, "MFA."), [])
    assert route.call_count == 3 and audit.events == []


@respx.mock
def test_jev_triage_sorts_documents_by_chunk_id(settings: Settings) -> None:
    import json

    route = respx.post(URL).respond(200, json=_answer(0.9, "addressed"))
    ev = [_chunk("d:p002:c000", "two"), _chunk("d:p001:c000", "one")]
    _jev(settings)[0].triage(CONTROL, ev)
    docs = json.loads(route.calls[0].request.content)["state"]["documents"]
    assert [x["chunk_id"] for x in docs] == ["d:p001:c000", "d:p002:c000"]


@respx.mock
def test_jev_audit_stage_actor_and_no_document_text(settings: Settings) -> None:
    respx.post(URL).respond(200, json=_answer(0.9, "addressed"))
    jev, audit, cost = _jev(settings)
    jev.triage(CONTROL, [_chunk("d:p001:c000", "SECRET-DOC-TEXT")])
    e = audit.events[0]
    assert e.stage == "jev.triage" and e.actor.startswith("jev/") and e.cached is False
    assert "SECRET-DOC-TEXT" not in e.model_dump_json()
    assert cost.summary().decider_calls == 1


def test_budget_error_propagates_and_is_not_swallowed_by_fallback(
    settings: Settings,
) -> None:
    audit = FakeAudit()
    rule = RuleDecider(settings.decision.rule)

    class Budget:
        name = "jev"

        def triage(self, *a: Any) -> Any:
            raise BudgetExceededError("over")

    fb = FallbackDecider(Budget(), rule, audit, primary_name="jev")  # type: ignore[arg-type]
    with pytest.raises(BudgetExceededError):
        fb.triage(CONTROL, [])
    assert audit.events == []


# --- fallback ------------------------------------------------------------------------------------


class Good:
    name = "good"

    def __init__(self) -> None:
        self.calls = 0

    def triage(self, *a: Any) -> Any:
        self.calls += 1
        return RuleDecider.triage(RuleDecider.__new__(RuleDecider), *a)


def test_fallback_passes_primary_result_through_without_audit(settings: Settings) -> None:
    audit = FakeAudit()
    rule = RuleDecider(settings.decision.rule)

    class OK:
        name = "ok"

        def triage(self, control: Control, evidence: Sequence[ScoredChunk]) -> Any:
            return rule.triage(control, evidence)

        def verify(self, *a: Any) -> Any:
            return rule.verify(*a)

    fb = FallbackDecider(OK(), MockDecider(settings.decision.rule), audit, primary_name="ok")  # type: ignore[arg-type]
    d = fb.triage(CONTROL, [_chunk("d:p001:c000", "MFA is enforced.")])
    assert d.provider == "rule" and not d.fallback_used and audit.events == []


def test_fallback_does_not_catch_programming_errors(settings: Settings) -> None:
    class Bug:
        name = "bug"

        def triage(self, *a: Any) -> Any:
            raise KeyError("x")

    fb = FallbackDecider(Bug(), RuleDecider(settings.decision.rule), FakeAudit(), primary_name="b")  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        fb.triage(CONTROL, [])


def test_fallback_warns_once_across_gates_and_error_text_stays_out_of_audit(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    class Down:
        name = "jev"

        def triage(self, *a: Any) -> Any:
            raise DeciderError("secret-server-text")

        verify = triage

    audit = FakeAudit()
    fb = FallbackDecider(Down(), MockDecider(settings.decision.rule), audit, primary_name="jev")  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        fb.triage(CONTROL, [])
        fb.verify(CONTROL, _draft(DraftStatus.NO_EVIDENCE), [])
        fb.triage(CONTROL, [])
    assert sum("unavailable" in r.message for r in caplog.records) == 1
    assert len(audit.events) == 3
    assert all("secret-server-text" not in e.model_dump_json() for e in audit.events)
    assert audit.events[0].actor == "jev->mock"


def test_fallback_without_primary_warns_at_construction_with_reason(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        FallbackDecider(
            None, RuleDecider(settings.decision.rule), FakeAudit(),
            primary_name="jev", unavailable="no key set",
        )  # fmt: skip
    assert len(caplog.records) == 1 and "no key set" in caplog.records[0].message
    assert KEY not in caplog.records[0].message


def test_factory_without_key_warns_once_for_a_whole_run(
    settings_override: Any, caplog: pytest.LogCaptureFixture
) -> None:
    s = settings_override(decision={"provider": "jev"})
    audit = FakeAudit()
    deps = factory.DeciderDeps(
        object(), PromptLoader(ROOT / "prompts", s.prompts), audit, CostTracker(s.cost)
    )  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        d = factory.build_decider(s, deps)
        for _ in range(5):
            d.triage(CONTROL, [])
    assert sum("unavailable" in r.message for r in caplog.records) == 1
    assert [e.stage for e in audit.events] == ["decider_fallback"] * 5


# --- LLM judge -----------------------------------------------------------------------------------


class FixedLLM:
    provider, model = "ollama", "fake"

    def __init__(self, label: str = "addressed", error: Exception | None = None) -> None:
        self.label, self.error = label, error

    def complete_json(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[Any],
        *,
        purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[Any]:
        if self.error:
            raise self.error
        parsed = output_model(label=self.label, confidence=0.7, reason="")
        return LLMResult(
            parsed=parsed, usage=Usage(tokens_in=1, tokens_out=1), provider="ollama", model="fake"
        )


def _judge(s: Settings, llm: Any) -> tuple[LlmJudgeDecider, FakeAudit]:
    audit = FakeAudit()
    prompts = PromptLoader(ROOT / "prompts", s.prompts)
    return LlmJudgeDecider(llm, prompts, audit, CostTracker(s.cost), s.decision.rule), audit


@pytest.mark.parametrize("label", ["supported", "unsupported"])
def test_triage_wrong_kind_labels_never_skip_a_control(settings: Settings, label: str) -> None:
    d = _judge(settings, FixedLLM(label))[0].triage(CONTROL, [_chunk("d:p001:c000", "x")])
    assert (d.label, d.confidence) == (DecisionLabel.ADDRESSED, 0.0)


@pytest.mark.parametrize("label", ["addressed", "not_addressed"])
def test_verify_wrong_kind_labels_go_to_the_reviewer(settings: Settings, label: str) -> None:
    d = _judge(settings, FixedLLM(label))[0].verify(CONTROL, _draft(DraftStatus.MET, "MFA."), [])
    assert d.label is DecisionLabel.UNSUPPORTED and d.provider == "llm_judge"


def test_judge_right_kind_keeps_label_and_empty_reason_becomes_none(settings: Settings) -> None:
    d = _judge(settings, FixedLLM("not_addressed"))[0].triage(CONTROL, [])
    assert d.label is DecisionLabel.NOT_ADDRESSED and d.reason is None and d.confidence == 0.7


@pytest.mark.parametrize("err", [LLMError("down"), SchemaValidationError("bad")])
def test_judge_model_failure_audits_failed_stage_and_raises(
    settings: Settings, err: Exception
) -> None:
    judge, audit = _judge(settings, FixedLLM(error=err))
    with pytest.raises(type(err)):
        judge.triage(CONTROL, [_chunk("d:p001:c000", "x")])
    assert [e.stage for e in audit.events] == ["judge.failed"]
    assert audit.events[0].control_id == "IAM-02"


def test_judge_one_audit_event_per_gate_with_stage_judge(settings: Settings) -> None:
    judge, audit = _judge(settings, MockLLM(settings.decision.rule))
    judge.triage(CONTROL, [_chunk("d:p001:c000", "MFA is enforced.")])
    judge.verify(CONTROL, _draft(DraftStatus.MET, "MFA is enforced."), [])
    assert [e.stage for e in audit.events] == ["judge", "judge"]


def test_judge_handles_unicode_and_large_evidence(settings: Settings) -> None:
    judge, _ = _judge(settings, MockLLM(settings.decision.rule))
    big = "MFA ist erzwungen für alle Mitarbeiter 日本語 " * 5000
    ev = [_chunk("d:p001:c000", big)]
    d = judge.triage(CONTROL, ev)
    r = RuleDecider(settings.decision.rule).triage(CONTROL, ev)
    assert (d.label, d.confidence) == (r.label, r.confidence)


@pytest.mark.parametrize(
    ("status", "quotes"),
    [
        (DraftStatus.MET, ()),
        (DraftStatus.NO_EVIDENCE, ()),
        (DraftStatus.MET, ("MFA is enforced for all staff.",)),
        (DraftStatus.NOT_MET, ("We do not use MFA.",)),
        (DraftStatus.PARTIAL, ("MFA is planned for next quarter.",)),
        (DraftStatus.MET, ("Backups run nightly.",)),
    ],
)
def test_mock_judge_verify_agrees_with_rule_decider(
    settings: Settings, status: DraftStatus, quotes: tuple[str, ...]
) -> None:
    draft = _draft(status, *quotes)
    judge, _ = _judge(settings, MockLLM(settings.decision.rule))
    rule = RuleDecider(settings.decision.rule)
    a, b = judge.verify(CONTROL, draft, []), rule.verify(CONTROL, draft, [])
    assert (a.label, a.confidence) == (b.label, b.confidence)


@pytest.mark.parametrize("raw", [None, 0.0, 0.9])
def test_mock_judge_triage_agrees_with_rule_across_retrieval_scores(
    settings: Settings, raw: float | None
) -> None:
    ev = [_chunk("d:p001:c000", "Unrelated backup text.", raw)]
    a = _judge(settings, MockLLM(settings.decision.rule))[0].triage(CONTROL, ev)
    b = RuleDecider(settings.decision.rule).triage(CONTROL, ev)
    assert (a.label, a.confidence) == (b.label, b.confidence)


# --- rule / mock ---------------------------------------------------------------------------------


def test_mock_decider_equals_rule_except_for_the_name(settings: Settings) -> None:
    ev = [_chunk("d:p001:c000", "MFA is enforced for all staff.")]
    r = RuleDecider(settings.decision.rule).triage(CONTROL, ev)
    m = MockDecider(settings.decision.rule).triage(CONTROL, ev)
    assert (m.provider, r.provider) == ("mock", "rule")
    assert m.model_copy(update={"provider": "rule"}) == r


def test_rule_triage_is_order_independent_and_unicode_safe(settings: Settings) -> None:
    rule = RuleDecider(settings.decision.rule)
    a = _chunk("d:p001:c000", "MFA ist für alle Mitarbeiter Pflicht — «2FA» ✓")
    b = _chunk("d:p002:c000", "Nothing relevant.")
    assert rule.triage(CONTROL, [a, b]) == rule.triage(CONTROL, [b, a])
    assert rule.triage(CONTROL, [a, b]).label is DecisionLabel.ADDRESSED


# --- registry ------------------------------------------------------------------------------------


def test_registry_builders_return_matching_names(settings_override: Any) -> None:
    from typing import get_args

    from vendorguard.config_models import base

    assert set(factory.DECIDERS) == set(get_args(base.DeciderProvider))
    s = settings_override()
    deps = factory.DeciderDeps(
        MockLLM(s.decision.rule), PromptLoader(ROOT / "prompts", s.prompts), FakeAudit(),
        CostTracker(s.cost),
    )  # fmt: skip
    for name in ("rule", "mock", "llm_judge"):
        s2 = settings_override(decision={"provider": name})
        assert factory.build_decider(s2, deps).name == name
