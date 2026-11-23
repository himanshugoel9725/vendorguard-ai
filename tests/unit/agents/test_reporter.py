"""Reporter Agent, number guard, fallback summary and facts."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from vendorguard.agents.reporter import FALLBACK_STAGE, ReporterAgent
from vendorguard.config import Settings
from vendorguard.errors import LLMError
from vendorguard.models.audit import AuditEvent
from vendorguard.models.finding import ControlFinding, ControlStatus
from vendorguard.models.llm import ChatMessage, LLMResult, Usage
from vendorguard.models.run import ReassessmentDiff
from vendorguard.models.score import InherentRisk, InherentTier, RiskBand, RiskScore
from vendorguard.observability.cost_tracker import CostTracker
from vendorguard.providers.llm.mock import MockLLM
from vendorguard.reporting.facts import build_facts
from vendorguard.reporting.fallback_summary import fallback_summary
from vendorguard.utils.prompt_loader import PromptLoader
from vendorguard.utils.timeutil import utcnow
from vendorguard.verification.summary_guard import check_summary

ROOT = Path(__file__).resolve().parents[3]


def _finding(cid: str, status: str) -> ControlFinding:
    return ControlFinding(
        control_id=cid, status=ControlStatus(status), citations=[], rationale="", trace=[],
        review_rounds=0,
    )  # fmt: skip


FINDINGS = [_finding("IAM-02", "not_met"), _finding("DAT-01", "met"), _finding("LOG-03", "partial")]
SCORE = RiskScore(
    overall=45.5, band=RiskBand.HIGH, domain_scores={"IAM": 80.0, "DAT": 0.0},
    triggered_rules=["critical_control_floor: IAM-02 is not_met, so the band is at least high"],
)  # fmt: skip
FACTS = build_facts(
    "Quillfield 2", InherentRisk(tier=InherentTier.MEDIUM, reasons=[]), SCORE, FINDINGS
)


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, **fields: Any) -> AuditEvent:
        e = AuditEvent(run_id="r", seq=len(self.events), ts=utcnow(), decision=None, **fields)
        self.events.append(e)
        return e


class Says:
    provider, model = "ollama", "fake"

    def __init__(self, text: str | None = None, fail: bool = False) -> None:
        self.text, self.fail = text, fail
        self.messages: list[ChatMessage] = []

    def complete_json(
        self, messages: Sequence[ChatMessage], output_model: type[Any], *, purpose: str,
        hints: Mapping[str, Any] | None = None,
    ) -> LLMResult[Any]:  # fmt: skip
        self.messages = list(messages)
        if self.fail:
            raise LLMError("down")
        return LLMResult(
            parsed=output_model(summary=self.text), usage=Usage(tokens_in=3, tokens_out=3),
            provider="ollama", model="fake",
        )  # fmt: skip


def _agent(s: Settings, llm: Any) -> tuple[ReporterAgent, FakeAudit]:
    audit = FakeAudit()
    prompts = PromptLoader(ROOT / "prompts", s.prompts)
    return ReporterAgent(llm, prompts, audit, CostTracker(s.cost), s.reporting), audit


def test_facts() -> None:
    assert FACTS["counts"] == {
        "met": 1,
        "partial": 1,
        "not_met": 1,
        "no_evidence": 0,
        "needs_human_review": 0,
    }
    assert FACTS["gaps"] == ["IAM-02", "LOG-03"] and FACTS["inherent_tier"] == "medium"
    diff = ReassessmentDiff(
        previous_run_id="p", new_gaps=["X-01"], resolved_gaps=[], changed=[], score_delta=-2.5
    )
    assert (
        build_facts("V", InherentRisk(tier=InherentTier.LOW, reasons=[]), SCORE, FINDINGS, diff)[
            "diff"
        ]["score_delta"]
        == -2.5
    )


def test_fallback_summary_passes_its_own_guard() -> None:
    text = fallback_summary(FACTS)
    assert "45.5" in text and "IAM-02, LOG-03" in text
    assert check_summary(text, FACTS, 150) == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("Score 45.5, 3 controls, IAM-02 open.", None),
        ("Quillfield 2 scored 45.5 with 80.0 in IAM.", None),
        ("Score 46 overall.", "number 46"),
        ("The score is 45.5 and 12 controls fail.", "number 12"),
        ("Gaps: IAM-02 and NET-09.", "control NET-09"),
        ("word " * 11, "more than the limit"),
    ],
)
def test_guard_table(text: str, fragment: str | None) -> None:
    problems = check_summary(text, FACTS, 10)
    if fragment is None:
        assert problems == []
    else:
        assert any(fragment in p for p in problems)


def test_guard_ignores_digits_in_the_vendor_name_only() -> None:
    assert check_summary("Quillfield 2 is fine.", FACTS, 50) == []
    assert check_summary("Quillfield 7 is fine.", FACTS, 50) != []


def test_mock_summary_passes_and_is_the_template(settings_override: Any) -> None:
    s: Settings = settings_override()
    agent, audit = _agent(s, MockLLM(s.decision.rule))
    assert agent.summarize(FACTS) == fallback_summary(FACTS)
    assert [e.stage for e in audit.events] == ["reporter"]


def test_a_hallucinated_number_triggers_the_fallback_and_an_audit_event(
    settings_override: Any,
) -> None:
    s: Settings = settings_override()
    agent, audit = _agent(s, Says("The vendor scored 97.3 and is excellent."))
    assert agent.summarize(FACTS) == fallback_summary(FACTS)
    assert [e.stage for e in audit.events] == ["reporter", FALLBACK_STAGE]


def test_a_good_model_summary_is_kept(settings_override: Any) -> None:
    s: Settings = settings_override()
    good = "Quillfield 2 scores 45.5 (high); IAM-02 is open."
    agent, audit = _agent(s, Says(good))
    assert agent.summarize(FACTS) == good and len(audit.events) == 1


def test_a_model_failure_falls_back_instead_of_failing_the_run(settings_override: Any) -> None:
    s: Settings = settings_override()
    agent, audit = _agent(s, Says(fail=True))
    assert agent.summarize(FACTS) == fallback_summary(FACTS)
    assert [e.stage for e in audit.events] == ["reporter.failed", FALLBACK_STAGE]


def test_prompt_has_the_facts_and_the_word_limit(settings_override: Any) -> None:
    s: Settings = settings_override()
    llm = Says("ok 45.5")
    _agent(s, llm)[0].summarize(FACTS)
    assert f"At most {s.reporting.summary_max_words} words" in llm.messages[0].content
    assert '"overall": 45.5' in llm.messages[1].content
