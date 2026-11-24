"""Mock LLM edge cases: intake patterns, mapper, judge confidence, reporter and ask templates."""

from collections.abc import Callable
from typing import Any

import pytest

from vendorguard.config import Settings
from vendorguard.models.decision import DecisionLabel
from vendorguard.models.finding import ExtractedEvidence
from vendorguard.models.outputs import JudgeOutput
from vendorguard.models.vendor import MAX_ITEMS, MAX_TEXT_CHARS, VendorProfile
from vendorguard.providers.llm.mock import MockLLM
from vendorguard.providers.llm.mock_intake import UNKNOWN_VENDOR, extract_profile


@pytest.fixture
def settings(settings_override: Callable[..., Settings]) -> Settings:
    return settings_override()


@pytest.fixture
def mock(settings: Settings) -> MockLLM:
    return MockLLM(settings.decision.rule)


def _cover(vendor: str = "Acme", rest: str = "") -> str:
    return f"Security & Trust Overview {vendor} Reporting period: 2025. {rest}"


def _profile(mock: MockLLM, text: str) -> VendorProfile:
    return mock.complete_json([], VendorProfile, purpose="intake", hints={"text": text}).parsed


# --- intake --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("We hold SOC 2 Type II.", ["SOC 2 Type II"]),
        ("We hold SOC 2 Type I.", ["SOC 2 Type I"]),
        ("We hold SOC2 Type 2.", ["SOC2 Type 2"]),
        ("We hold SOC 2.", ["SOC 2"]),
        ("ISO/IEC 27001:2022 certified.", ["ISO/IEC 27001:2022"]),
        ("ISO 27001 certified.", ["ISO 27001"]),
        ("PCI DSS and PCI-DSS.", ["PCI DSS", "PCI-DSS"]),
        ("HIPAA aligned.", ["HIPAA"]),
        ("Nothing certified here.", []),
    ],
)
def test_certification_variants(text: str, expected: list[str]) -> None:
    assert extract_profile(text)["certifications"] == expected


def test_certifications_deduplicated_in_order_and_whitespace_normalised() -> None:
    text = "HIPAA. ISO 27001. HIPAA. SOC 2.\nISO 27001. SOC  2"
    assert extract_profile(text)["certifications"] == ["HIPAA", "ISO 27001", "SOC 2"]


def test_certifications_capped_at_max_items() -> None:
    text = " ".join(f"ISO/IEC 27001:{2000 + i}" for i in range(30))
    assert len(extract_profile(text)["certifications"]) == MAX_ITEMS


def test_no_vendor_name_and_no_period(mock: MockLLM) -> None:
    profile = _profile(mock, "Just some prose without a cover page.")
    assert profile.vendor_name == UNKNOWN_VENDOR and profile.report_period is None
    assert profile.services == [] and profile.data_categories == []


def test_cover_page_fields_and_unicode(mock: MockLLM) -> None:
    text = (
        "Security & Trust Overview  Müller 日本\n GmbH  Reporting period: Jan–Dec 2025. "
        "Services: Zahlungen; Gehälter☃. Hosting: Frankfurt; Dublin. "
        "Key suppliers: Cloudé; Λάμδα. "
    )
    p = _profile(mock, text)
    assert p.vendor_name == "Müller 日本 GmbH" and p.report_period == "Jan–Dec 2025"
    assert p.services == ["Zahlungen", "Gehälter☃"]
    assert p.hosting == ["Frankfurt", "Dublin"] and p.subprocessors == ["Cloudé", "Λάμδα"]


def test_lists_cut_to_20_items_and_200_chars(mock: MockLLM) -> None:
    items = "; ".join(f"item{i}" for i in range(30))
    assert len(_profile(mock, _cover(rest=f"Services: {items}.")).services) == MAX_ITEMS
    long = "x" * 500
    services = _profile(mock, _cover(rest=f"Services: {long}; short.")).services
    assert services == ["x" * MAX_TEXT_CHARS, "short"]


def test_very_long_vendor_name_is_cut(mock: MockLLM) -> None:
    assert len(_profile(mock, _cover("N" * 1000)).vendor_name) == MAX_TEXT_CHARS


def test_empty_items_are_dropped() -> None:
    assert extract_profile("Services: a;; ;b.")["services"] == ["a", "b"]


def test_business_contact_only_gives_none_category() -> None:
    assert extract_profile("Data: business contact details only.")["data_categories"] == ["none"]
    both = extract_profile("Business contact details only, plus payroll files.")
    assert both["data_categories"] == ["financial"]


def test_credentials_cue_is_narrow() -> None:
    assert extract_profile("We help users reset forgotten passwords.")["data_categories"] == []
    assert "credentials" in extract_profile("We store customer login details.")["data_categories"]


# --- mapper --------------------------------------------------------------------------------------


def _map(mock: MockLLM, chunks: list[dict[str, Any]], keywords: list[str], **extra: Any) -> Any:
    hints = {"keywords": keywords, "chunks": chunks, **extra}
    return mock.complete_json([], ExtractedEvidence, purpose="mapper", hints=hints).parsed


def test_mapper_empty_inputs_give_no_evidence(mock: MockLLM) -> None:
    for chunks, keywords in [
        ([], ["mfa"]),
        ([{"chunk_id": "a", "text": ""}], ["mfa"]),
        ([{"chunk_id": "a", "text": "MFA is on."}], []),
    ]:
        out = _map(mock, chunks, keywords)
        assert out.citations == []


def test_mapper_match_only_in_second_chunk(mock: MockLLM) -> None:
    chunks = [{"chunk_id": "d:c000", "text": "Nothing."}, {"chunk_id": "d:c001", "text": "MFA on."}]
    out = _map(mock, chunks, ["mfa"])
    assert out.citations[0].chunk_id == "d:c001"


def test_mapper_chunks_are_read_in_document_order_not_list_order(mock: MockLLM) -> None:
    chunks = [{"chunk_id": f"d:c{i:03d}", "text": f"MFA mention {i}."} for i in (5, 1, 3)]
    assert _map(mock, chunks, ["mfa"]).citations[0].chunk_id == "d:c001"


def test_mapper_many_chunks_and_extra_fields(mock: MockLLM) -> None:
    chunks = [
        {"chunk_id": f"d:c{i:03d}", "text": "filler." if i < 499 else "MFA yes.", "score": 0.1}
        for i in range(500)
    ]
    assert _map(mock, chunks, ["mfa"]).citations[0].chunk_id == "d:c499"


def test_mapper_quote_limit_of_one_char(mock: MockLLM) -> None:
    out = _map(mock, [{"chunk_id": "a", "text": "MFA is on."}], ["mfa"], max_quote_chars=1)
    assert out.citations[0].quote == "M"


def test_mapper_is_deterministic(mock: MockLLM) -> None:
    chunks = [{"chunk_id": "a", "text": "MFA is planned."}]
    assert _map(mock, chunks, ["mfa"]) == _map(mock, chunks, ["mfa"])


# --- judge ---------------------------------------------------------------------------------------

KW = ["alpha", "beta", "gamma", "delta"]


def _triage(mock: MockLLM, evidence: list[str], keywords: list[str] = KW) -> JudgeOutput:
    hints = {"task": "triage", "keywords": keywords, "evidence": evidence}
    return mock.complete_json([], JudgeOutput, purpose="judge", hints=hints).parsed


def test_triage_confidence_values(mock: MockLLM, settings: Settings) -> None:
    needed = max(settings.decision.rule.triage_min_keyword_hits, 1)
    none = _triage(mock, ["nothing relevant"])
    assert (none.label, none.confidence) == (DecisionLabel.NOT_ADDRESSED, 1.0)
    if needed > 1:
        partial = _triage(mock, ["alpha only"])
        assert (partial.label, partial.confidence) == (DecisionLabel.NOT_ADDRESSED, 0.5)
    enough = _triage(mock, [" ".join(KW[:needed])])
    assert enough.label is DecisionLabel.ADDRESSED
    assert enough.confidence == pytest.approx(0.5 + 0.5 * needed / len(KW))
    assert _triage(mock, [" ".join(KW)]).confidence == 1.0


def test_triage_confidence_capped_with_empty_keywords_or_evidence(mock: MockLLM) -> None:
    out = _triage(mock, [], keywords=[])
    assert out.label is DecisionLabel.NOT_ADDRESSED and out.confidence == 1.0


def _verify(mock: MockLLM, status: str, quotes: list[str]) -> JudgeOutput:
    hints = {"task": "verify", "keywords": KW, "status": status, "quotes": quotes}
    return mock.complete_json([], JudgeOutput, purpose="judge", hints=hints).parsed


def test_verify_statuses(mock: MockLLM) -> None:
    full = "alpha beta gamma delta"
    assert _verify(mock, "met", [f"We have {full}."]).label is DecisionLabel.SUPPORTED
    assert _verify(mock, "partial", [f"{full} is planned."]).label is DecisionLabel.SUPPORTED
    assert _verify(mock, "not_met", [f"{full} is not enforced."]).label is DecisionLabel.SUPPORTED
    assert _verify(mock, "met", [f"{full} is planned."]).label is DecisionLabel.UNSUPPORTED
    assert _verify(mock, "not_met", [f"{full} is fine."]).label is DecisionLabel.UNSUPPORTED
    assert _verify(mock, "met", ["unrelated text"]).label is DecisionLabel.UNSUPPORTED
    assert _verify(mock, "no_evidence", []).label is DecisionLabel.SUPPORTED
    assert _verify(mock, "no_evidence", ["alpha"]).label is DecisionLabel.UNSUPPORTED
    assert _verify(mock, "met", []).confidence == 1.0
