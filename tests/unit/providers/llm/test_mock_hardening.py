"""Phase 4 review fixes: malformed mock hints give LLMError; change words are whole words."""

from collections.abc import Callable
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.errors import LLMError
from vendorguard.models.finding import DraftFinding
from vendorguard.models.outputs import AskOutput, JudgeOutput, SummaryOutput
from vendorguard.providers.llm.mock import MockLLM


@pytest.fixture
def mock(settings_override: Callable[..., Settings]) -> MockLLM:
    return MockLLM(settings_override().decision.rule)


@pytest.mark.parametrize(
    ("model", "purpose", "hints"),
    [
        (DraftFinding, "mapper", {"keywords": ["mfa"], "chunks": [{"text": "no id"}]}),
        (DraftFinding, "mapper", {"keywords": ["mfa"], "chunks": [{"chunk_id": "a"}]}),
        (DraftFinding, "mapper", {"keywords": 5, "chunks": []}),
        (DraftFinding, "mapper", {"keywords": ["x"], "chunks": "text"}),
        (JudgeOutput, "judge", {"task": "verify", "keywords": [], "status": "bogus", "quotes": []}),
        (JudgeOutput, "judge", {"task": "triage", "keywords": ["x"], "evidence": 5}),
        (SummaryOutput, "reporter", {"vendor_name": "A", "overall": 1, "band": "low"}),
        (
            SummaryOutput,
            "reporter",
            {"vendor_name": "A", "overall": "x", "band": "low", "counts": {}},
        ),
        (AskOutput, "ask", {"question": "q", "runs": [{"run_id": "r"}]}),
        (AskOutput, "ask", {"question": "q", "runs": 5}),
    ],
)
def test_malformed_hints_are_llm_errors_not_raw_exceptions(
    mock: MockLLM, model: type, purpose: str, hints: dict[str, Any]
) -> None:
    with pytest.raises(LLMError, match=rf"malformed hints for '{purpose}'|needs the hint"):
        mock.complete_json([], model, purpose=purpose, hints=hints)


def test_the_error_names_only_the_exception_class_not_the_hint_values(mock: MockLLM) -> None:
    with pytest.raises(LLMError) as info:
        mock.complete_json(
            [],
            DraftFinding,
            purpose="mapper",
            hints={"keywords": ["x"], "chunks": [{"text": "SECRET-DOC"}]},
        )
    assert "SECRET-DOC" not in str(info.value) and "KeyError" in str(info.value)


def _runs() -> list[dict[str, Any]]:
    new = {"run_id": "run_new", "overall": 10.0, "band": "low", "findings": {"IAM-04": "met"}}
    old = {"run_id": "run_old", "overall": 20.0, "band": "low", "findings": {"IAM-04": "partial"}}
    return [new, old]


@pytest.mark.parametrize(
    ("question", "is_diff"),
    [
        ("What changed since last year?", True),
        ("Did anything improve?", True),
        ("Show the differences", True),
        ("Any new gaps?", True),
        ("Is the vendor difficult to assess?", False),  # 'diff' inside another word
        ("Is the vendor unchanged in spirit?", False),
        ("Tell me about the exchange rate", False),
        ("How are they doing?", False),
    ],
)
def test_change_questions_match_whole_words_only(
    mock: MockLLM, question: str, is_diff: bool
) -> None:
    answer = mock.complete_json(
        [], AskOutput, purpose="ask", hints={"question": question, "runs": _runs()}
    )
    assert ("Between run" in answer.parsed.text) is is_diff
