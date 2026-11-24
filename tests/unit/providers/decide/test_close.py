"""close() of the deciders, and the llm_judge fallback built by the factory."""

from pathlib import Path
from typing import Any

import pytest

from vendorguard import factory
from vendorguard.config import Settings
from vendorguard.errors import LLMError, SchemaValidationError
from vendorguard.models.audit import AuditEvent
from vendorguard.models.control import Control
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.evidence import Chunk, DraftCitation, ScoredChunk
from vendorguard.models.finding import DraftFinding, DraftStatus
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.decide.fallback import FallbackDecider
from vendorguard.providers.decide.jev import JevDecider
from vendorguard.providers.decide.rule import RuleDecider
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow

ROOT = Path(__file__).resolve().parents[4]
CONTROL = Control(
    id="IAM-02", title="MFA", domain="IAM", criticality="critical", iso27001=["8.5"],
    nist_csf=["PR.AA"], requirement="MFA is enforced.", met_criteria="MFA for all access.",
    keywords=["MFA", "2FA"],
)  # fmt: skip
TEXT = "MFA is enforced for all staff."
EVIDENCE = [
    ScoredChunk(
        chunk=Chunk(chunk_id="d:p001:c000", doc_id="d", page=1, text=TEXT, char_start=0,
                    char_end=len(TEXT)),
        score=1.0, bm25=1.0, bm25_raw=5.0,
    )
]  # fmt: skip


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, **fields: Any) -> AuditEvent:
        e = AuditEvent(run_id="r", seq=len(self.events), ts=utcnow(), **fields)
        self.events.append(e)
        return e


class Closable:
    name = "closable"

    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class FailingLLM:
    provider, model = "mock", "mock"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def complete_json(self, *a: Any, **k: Any) -> Any:
        raise self.exc


@pytest.fixture
def s(settings_override: Any) -> Settings:
    out: Settings = settings_override(decision={"provider": "llm_judge"})
    return out


def test_fallback_close_closes_the_primary(s: Settings) -> None:
    primary = Closable()
    fb = FallbackDecider(primary, RuleDecider(s.decision.rule), FakeAudit(), primary_name="x")  # type: ignore[arg-type]
    fb.close()
    assert primary.closed == 1


def test_fallback_close_without_primary_or_close_is_a_noop(s: Settings) -> None:
    rule = RuleDecider(s.decision.rule)
    FallbackDecider(None, rule, FakeAudit(), primary_name="x").close()
    FallbackDecider(rule, rule, FakeAudit(), primary_name="x").close()


def test_fallback_close_is_repeatable(s: Settings) -> None:
    primary = Closable()
    fb = FallbackDecider(primary, RuleDecider(s.decision.rule), FakeAudit(), primary_name="x")  # type: ignore[arg-type]
    fb.close()
    fb.close()
    assert primary.closed == 2


def test_jev_decider_close_closes_its_client(s: Settings) -> None:
    client = Closable()
    JevDecider(client, s.decision.jev, FakeAudit(), CostTracker(s.cost)).close()  # type: ignore[arg-type]
    assert client.closed == 1


@pytest.mark.parametrize("exc", [SchemaValidationError("bad"), LLMError("down")])
def test_factory_wraps_llm_judge_so_failures_fall_back_to_the_rules(
    s: Settings, exc: Exception
) -> None:
    audit = FakeAudit()
    deps = factory.DeciderDeps(
        FailingLLM(exc),
        PromptLoader(ROOT / "prompts", s.prompts),
        audit,
        CostTracker(s.cost),  # type: ignore[arg-type]
    )
    d = factory.build_decider(s, deps)
    assert isinstance(d, FallbackDecider) and d.name == "llm_judge"
    rule = RuleDecider(s.decision.rule)
    t = d.triage(CONTROL, EVIDENCE)
    assert t.fallback_used and (t.label, t.confidence) == (
        (r := rule.triage(CONTROL, EVIDENCE)).label,
        r.confidence,
    )
    draft = DraftFinding(
        status=DraftStatus.MET,
        citations=[DraftCitation(chunk_id="d:p001:c000", quote=TEXT)],
        rationale="r",
    )
    v = d.verify(CONTROL, draft, EVIDENCE)
    assert v.fallback_used and v.label in (DecisionLabel.SUPPORTED, DecisionLabel.UNSUPPORTED)
    fallbacks = [e for e in audit.events if e.stage == "decider_fallback"]
    assert len(fallbacks) == 2
    blobs = [e.model_dump_json() for e in fallbacks]
    assert all("bad" not in b and "down" not in b for b in blobs)
    d.close()  # the judge holds no client: must not raise
