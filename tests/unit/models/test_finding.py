"""Tests for vendorguard.models.finding."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from vendorguard.models.decision import Decision, DecisionLabel, Gate, GateTrace
from vendorguard.models.evidence import Citation, DraftCitation
from vendorguard.models.finding import (
    MAX_CITATIONS,
    MAX_RATIONALE_WORDS,
    ControlFinding,
    ControlStatus,
    DraftFinding,
    DraftStatus,
    Override,
)

AT = datetime(2025, 1, 1, tzinfo=UTC)


def make_draft(**kw: object) -> DraftFinding:
    data: dict = {
        "status": "met",
        "citations": [DraftCitation(chunk_id="c", quote="q")],
        "rationale": "because",
    }
    data.update(kw)
    return DraftFinding(**data)


def make_override(**kw: object) -> Override:
    data: dict = {"analyst": "ann", "new_status": DraftStatus.MET, "reason": "r", "at": AT}
    data.update(kw)
    return Override(**data)


def make_finding(**kw: object) -> ControlFinding:
    data: dict = {
        "control_id": "AC-01",
        "status": ControlStatus.PARTIAL,
        "citations": [Citation(chunk_id="c", quote="q", valid=True)],
        "rationale": "r",
        "trace": [
            GateTrace(
                gate=Gate.TRIAGE,
                decision=Decision(label=DecisionLabel.ADDRESSED, confidence=0.9, provider="m"),
                round=0,
            )
        ],
        "review_rounds": 0,
    }
    data.update(kw)
    return ControlFinding(**data)


def test_status_enums() -> None:
    assert len(DraftStatus) == 4
    assert len(ControlStatus) == 5
    assert ControlStatus.NEEDS_HUMAN_REVIEW.value == "needs_human_review"
    assert {s.value for s in DraftStatus} < {s.value for s in ControlStatus}


def test_draft_roundtrip() -> None:
    d = make_draft()
    assert DraftFinding.model_validate_json(d.model_dump_json()) == d


def test_draft_citation_limit() -> None:
    cits = [DraftCitation(chunk_id=f"c{i}", quote="q") for i in range(MAX_CITATIONS)]
    assert len(make_draft(citations=cits).citations) == MAX_CITATIONS
    assert make_draft(citations=[]).citations == []
    with pytest.raises(ValidationError):
        make_draft(citations=[*cits, DraftCitation(chunk_id="x", quote="q")])


def test_draft_rationale_words() -> None:
    assert make_draft(rationale=" ".join(["w"] * MAX_RATIONALE_WORDS))
    with pytest.raises(ValidationError):
        make_draft(rationale=" ".join(["w"] * (MAX_RATIONALE_WORDS + 1)))
    with pytest.raises(ValidationError):
        make_draft(rationale="")


def test_draft_status_rejects_review() -> None:
    with pytest.raises(ValidationError):
        make_draft(status="needs_human_review")


def test_draft_schema() -> None:
    schema = DraftFinding.model_json_schema()
    assert set(schema["required"]) >= {"status", "citations", "rationale"}
    assert schema["properties"]["citations"]["maxItems"] == MAX_CITATIONS
    cit = schema["$defs"]["DraftCitation"]
    assert set(cit["properties"]) == {"chunk_id", "quote"}


def test_override_rules() -> None:
    o = make_override()
    assert Override.model_validate_json(o.model_dump_json()) == o
    with pytest.raises(ValidationError):
        make_override(new_status="needs_human_review")
    with pytest.raises(ValidationError):
        make_override(analyst="")
    with pytest.raises(ValidationError):
        make_override(reason="")
    with pytest.raises(ValidationError):
        make_override(at=datetime(2025, 1, 1))


def test_effective_status() -> None:
    f = make_finding()
    assert f.effective_status is ControlStatus.PARTIAL
    g = make_finding(override=make_override(new_status=DraftStatus.NOT_MET))
    assert g.effective_status is ControlStatus.NOT_MET
    assert isinstance(g.effective_status, ControlStatus)
    assert g.status is ControlStatus.PARTIAL


def test_finding_roundtrip_with_override() -> None:
    f = make_finding(override=make_override())
    assert ControlFinding.model_validate_json(f.model_dump_json()) == f


def test_finding_limits() -> None:
    cits = [Citation(chunk_id=f"c{i}", quote="q") for i in range(MAX_CITATIONS + 1)]
    with pytest.raises(ValidationError):
        make_finding(citations=cits)
    with pytest.raises(ValidationError):
        make_finding(review_rounds=-1)
    with pytest.raises(ValidationError):
        make_finding(control_id="")
    assert make_finding(status="needs_human_review").status is ControlStatus.NEEDS_HUMAN_REVIEW


def test_finding_citations_are_citation_objects() -> None:
    f = make_finding()
    assert all(isinstance(c, Citation) for c in f.citations)
    with pytest.raises(ValidationError):
        make_finding().model_validate({**f.model_dump(), "bogus": 1})
