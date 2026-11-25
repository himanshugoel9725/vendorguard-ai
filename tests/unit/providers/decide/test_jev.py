"""Jev client contract (fixtures + respx), the Jev decider and the fallback decider."""

import json
from pathlib import Path
from typing import Any

import pytest
import respx

from vendorguard import factory
from vendorguard.config import Settings
from vendorguard.errors import ConfigError, DeciderError
from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import Control
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.evidence import Chunk, DraftCitation, ScoredChunk
from vendorguard.models.finding import DraftFinding, DraftStatus
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.decide.fallback import FallbackDecider
from vendorguard.providers.decide.jev import JevDecider
from vendorguard.providers.decide.jev_client import JevClient
from vendorguard.providers.decide.rule import RuleDecider
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow

ROOT = Path(__file__).resolve().parents[4]
FIX = ROOT / "tests" / "fixtures" / "jev"
URL = "https://api.typesafe.ai/v1/systemone"
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


def _ev(text: str = "MFA is enforced for all staff.") -> list[ScoredChunk]:
    c = Chunk(
        chunk_id="d:p001:c000", doc_id="d", page=1, text=text, char_start=0, char_end=len(text)
    )
    return [ScoredChunk(chunk=c, score=1.0, bm25=1.0)]


def _draft(status: DraftStatus = DraftStatus.MET) -> DraftFinding:
    return DraftFinding(
        status=status, citations=[DraftCitation(chunk_id="d:p001:c000", quote="MFA is enforced.")],
        rationale="r",
    )  # fmt: skip


@pytest.fixture
def settings(settings_override: Any) -> Settings:
    s: Settings = settings_override(decision={"jev": {"api_key": KEY, "max_calls_per_run": 2}})
    return s


def _client(s: Settings) -> JevClient:
    return JevClient(s.decision.jev, s.llm)


def _stack(s: Settings) -> tuple[JevDecider, FakeAudit, CostTracker]:
    audit, cost = FakeAudit(), CostTracker(s.cost)
    return JevDecider(_client(s), s.decision.jev, audit, cost), audit, cost


@respx.mock
def test_client_contract_on_the_fixture(settings: Settings) -> None:
    route = respx.post(URL).respond(200, json=json.loads((FIX / "noul_reply.json").read_text()))
    answers, usage = _client(settings).ask({"x": 1}, {"addressed": {"type": "noul"}})
    assert answers == {"addressed": 0.9} and (usage.tokens_in, usage.tokens_out) == (420, 3)
    req = route.calls[0].request
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == "jev-latest" and set(body) == {"model", "state", "questions"}


@respx.mock
def test_refusal_is_an_error(settings: Settings) -> None:
    respx.post(URL).respond(200, json=json.loads((FIX / "refusal_reply.json").read_text()))
    with pytest.raises(DeciderError, match="no yes/no answer"):
        _client(settings).ask({}, {"addressed": {"type": "noul"}})


@respx.mock
@pytest.mark.parametrize("status", [401, 402, 403])
def test_auth_errors_never_echo_the_server_or_key(settings: Settings, status: int) -> None:
    respx.post(URL).respond(status, json={"error": {"message": f"bad {KEY}"}})
    with pytest.raises(DeciderError) as exc:
        _client(settings).ask({}, {"addressed": {}})
    assert KEY not in str(exc.value) and "bad" not in str(exc.value)


@respx.mock
def test_other_status_and_bad_json_are_errors_without_the_key(settings: Settings) -> None:
    respx.post(URL).respond(400, json={"error": {"message": f"oops {KEY}"}})
    with pytest.raises(DeciderError) as exc:
        _client(settings).ask({}, {"a": {}})
    assert "HTTP 400" in str(exc.value) and KEY not in str(exc.value)
    respx.post(URL).respond(200, json={"answers": {}})
    with pytest.raises(DeciderError, match="unexpected reply"):
        _client(settings).ask({}, {"a": {}})


def test_client_requires_a_key_and_https(settings_override: Any) -> None:
    s = settings_override()
    with pytest.raises(ConfigError, match="VG_DECISION__JEV__API_KEY"):
        JevClient(s.decision.jev, s.llm)
    s = settings_override(decision={"jev": {"api_key": KEY, "base_url": "http://example.com/x"}})
    with pytest.raises(ConfigError, match="https"):
        JevClient(s.decision.jev, s.llm)


@respx.mock
@pytest.mark.parametrize(
    ("p", "label", "conf"), [(0.9, "addressed", 0.9), (0.2, "not_addressed", 0.8)]
)
def test_triage_maps_probability_to_a_decision(
    settings: Settings, p: float, label: str, conf: float
) -> None:
    respx.post(URL).respond(
        200,
        json={
            "answers": {"addressed": {"type": "noul", "noul": p}},
            "usage": {"input_tokens": 100, "output_tokens": 1},
        },
    )
    d = _stack(settings)[0].triage(CONTROL, _ev())
    assert (d.label.value, d.confidence, d.provider) == (label, conf, "jev")


@respx.mock
def test_verify_audits_counts_cost_and_caps_calls(settings: Settings) -> None:
    respx.post(URL).respond(
        200,
        json={
            "answers": {"supported": {"type": "noul", "noul": 0.97}},
            "usage": {"input_tokens": 1000, "output_tokens": 0},
        },
    )
    jev, audit, cost = _stack(settings)
    assert jev.verify(CONTROL, _draft(), _ev()).label is DecisionLabel.SUPPORTED
    assert audit.events[0].stage == "jev.verify" and audit.events[0].control_id == "IAM-02"
    assert cost.summary().decider_calls == 1 and cost.summary().usd > 0
    jev.verify(CONTROL, _draft(), _ev())
    with pytest.raises(DeciderError, match="max_calls_per_run"):
        jev.verify(CONTROL, _draft(), _ev())


@respx.mock
def test_state_carries_documents_as_data_and_the_status(settings: Settings) -> None:
    route = respx.post(URL).respond(
        200,
        json={
            "answers": {"supported": {"type": "noul", "noul": 1.0}},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        },
    )
    _stack(settings)[0].verify(CONTROL, _draft(DraftStatus.PARTIAL), _ev())
    body = json.loads(route.calls[0].request.content)
    assert body["state"]["proposed_status"] == "partial"
    assert body["state"]["quotes"][0]["text"] == "MFA is enforced."
    assert "untrusted" in body["questions"]["supported"]["instructions"]


class Boom:
    name = "jev"

    def triage(self, *a: Any) -> Any:
        raise DeciderError("down")

    verify = triage


def test_fallback_on_error_marks_decision_and_audits_once_per_use(settings: Settings) -> None:
    audit = FakeAudit()
    rule = RuleDecider(settings.decision.rule)
    fb = FallbackDecider(Boom(), rule, audit, primary_name="jev")
    d = fb.triage(CONTROL, _ev())
    assert d.provider == "rule" and d.fallback_used
    assert fb.verify(CONTROL, _draft(), _ev()).fallback_used
    assert [e.stage for e in audit.events] == ["decider_fallback"] * 2
    assert audit.events[0].actor == "jev->rule" and "down" not in audit.events[0].output_hash


def test_fallback_when_unavailable_warns_once(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    audit = FakeAudit()
    fb = FallbackDecider(
        None, RuleDecider(settings.decision.rule), audit, primary_name="jev", unavailable="no key"
    )
    fb.triage(CONTROL, _ev())
    fb.triage(CONTROL, _ev())
    assert sum("unavailable" in r.message for r in caplog.records) == 1


def test_factory_without_a_key_completes_through_the_fallback(settings_override: Any) -> None:
    s = settings_override(decision={"provider": "jev"})
    audit = FakeAudit()
    deps = factory.DeciderDeps(
        object(), PromptLoader(ROOT / "prompts", s.prompts), audit, CostTracker(s.cost)
    )  # type: ignore[arg-type]
    d = factory.build_decider(s, deps)
    out = d.triage(CONTROL, _ev())
    assert out.fallback_used and out.provider == "rule" and d.name == "jev"
    assert audit.events[0].stage == "decider_fallback"


def test_factory_with_a_key_builds_the_jev_decider(settings_override: Any) -> None:
    s = settings_override(decision={"provider": "jev", "jev": {"api_key": KEY}})
    deps = factory.DeciderDeps(
        object(), PromptLoader(ROOT / "prompts", s.prompts), FakeAudit(), CostTracker(s.cost)
    )  # type: ignore[arg-type]
    assert isinstance(factory.build_decider(s, deps)._primary, JevDecider)  # type: ignore[attr-defined]  # noqa: SLF001


def test_mock_decider_name() -> None:
    from vendorguard.providers.decide.mock import MockDecider

    assert MockDecider.name == "mock"
