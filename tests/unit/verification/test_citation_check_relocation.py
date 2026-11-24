"""Citation relocation: a quote attached to the wrong chunk is moved to the chunk that has it."""

from collections.abc import Callable

import pytest

from vendorguard.agents.derive import derive_finding
from vendorguard.config import Settings
from vendorguard.models.control import Control
from vendorguard.models.evidence import Chunk, DraftCitation
from vendorguard.models.finding import DraftStatus, ExtractedEvidence
from vendorguard.verification.citation_check import CitationChecker

SENTENCE = "All data is encrypted at rest using AES-256."
OTHER = "Backups are tested every quarter by the infrastructure team."


def _chunk(cid: str, text: str, page: int = 1, doc: str = "d") -> Chunk:
    return Chunk(chunk_id=cid, doc_id=doc, page=page, text=text, char_start=0, char_end=len(text))


@pytest.fixture
def settings(settings_override: Callable[..., Settings]) -> Settings:
    return settings_override()


@pytest.fixture
def checker(settings: Settings) -> CitationChecker:
    return CitationChecker(settings.verification)


def _check(
    checker: CitationChecker, chunks: list[Chunk], cid: str, quote: str, status: DraftStatus
):
    return checker.check(status, [DraftCitation(chunk_id=cid, quote=quote)], chunks)


def test_quote_in_another_chunk_is_relocated_with_its_page_and_doc(
    checker: CitationChecker,
) -> None:
    chunks = [_chunk("a:p001:c000", OTHER, 1, "a"), _chunk("b:p004:c000", SENTENCE, 4, "b")]
    r = _check(checker, chunks, "a:p001:c000", SENTENCE, DraftStatus.MET)
    c = r.citations[0]
    assert r.ok and r.problems == []
    assert (c.chunk_id, c.doc_id, c.page) == ("b:p004:c000", "b", 4)
    assert c.valid and c.relocated and c.similarity == 1.0


def test_unknown_chunk_id_with_the_quote_elsewhere_is_relocated(checker: CitationChecker) -> None:
    chunks = [_chunk("d:p001:c000", OTHER), _chunk("d:p002:c000", SENTENCE, 2)]
    r = _check(checker, chunks, "does-not-exist", SENTENCE, DraftStatus.MET)
    assert r.ok and r.citations[0].chunk_id == "d:p002:c000" and r.citations[0].relocated


def test_quote_found_nowhere_is_invalid_with_the_old_problem_text(
    checker: CitationChecker,
) -> None:
    chunks = [_chunk("d:p001:c000", OTHER), _chunk("d:p002:c000", SENTENCE)]
    r = _check(
        checker, chunks, "d:p001:c000", "ZEBRA unrelated fabricated sentence", DraftStatus.MET
    )
    assert not r.ok and not r.citations[0].valid and not r.citations[0].relocated
    assert r.problems[0] == "citation 1 is not found in chunk d:p001:c000"


def test_named_chunk_match_is_not_relocated_even_if_another_chunk_has_it_too(
    checker: CitationChecker,
) -> None:
    chunks = [_chunk("d:p001:c000", SENTENCE), _chunk("d:p002:c000", SENTENCE, 2)]
    r = _check(checker, chunks, "d:p002:c000", SENTENCE, DraftStatus.MET)
    c = r.citations[0]
    assert r.ok and c.chunk_id == "d:p002:c000" and c.page == 2 and not c.relocated


def test_same_quote_in_two_other_chunks_goes_to_the_lowest_chunk_id(
    checker: CitationChecker,
) -> None:
    chunks = [
        _chunk("d:p003:c000", SENTENCE, 3),
        _chunk("d:p002:c000", SENTENCE, 2),
        _chunk("d:p001:c000", OTHER, 1),
    ]
    r = _check(checker, chunks, "d:p001:c000", SENTENCE, DraftStatus.MET)
    assert r.citations[0].chunk_id == "d:p002:c000" and r.citations[0].relocated


def test_a_higher_score_beats_a_lower_chunk_id(checker: CitationChecker) -> None:
    near = SENTENCE.replace("AES-256", "AES-25X")
    chunks = [_chunk("d:p001:c000", near), _chunk("d:p002:c000", SENTENCE, 2)]
    r = _check(checker, chunks, "d:p009:c000", SENTENCE, DraftStatus.MET)
    assert r.citations[0].chunk_id == "d:p002:c000" and r.citations[0].similarity == 1.0


def test_fuzzy_relocation_keeps_the_source_words(checker: CitationChecker) -> None:
    source = "Multi-factor authentication is enforced for every administrator and every employee."
    model = "Multi-factor authentication is enforced for every administrator and employee"
    chunks = [_chunk("d:p001:c000", OTHER), _chunk("d:p002:c000", source, 2)]
    r = _check(checker, chunks, "d:p001:c000", model, DraftStatus.MET)
    c = r.citations[0]
    assert c.relocated and c.valid and c.similarity is not None and c.similarity < 1.0
    assert c.quote != model and "every employee" in c.quote


def test_a_deleted_not_cannot_pass_as_met_after_derive(
    checker: CitationChecker, settings: Settings
) -> None:
    source = "Multi-factor authentication is not enforced for staff accounts."
    model = "Multi-factor authentication is enforced for staff accounts."
    chunks = [_chunk("d:p001:c000", OTHER), _chunk("d:p002:c000", source, 2)]
    r = _check(checker, chunks, "d:p001:c000", model, DraftStatus.MET)
    if not r.ok:  # similarity under the configured floor: rejected, which is also safe
        assert not r.citations[0].valid
        return
    assert "not enforced" in r.citations[0].quote
    control = Control(
        id="IAM-02", title="MFA", domain="IAM", criticality="high", iso27001=["8.5"],
        nist_csf=["PR.AA"], requirement="MFA.", met_criteria="MFA.",
        keywords=["multi-factor authentication"],
    )  # fmt: skip
    extracted = ExtractedEvidence(
        citations=[DraftCitation(chunk_id=c.chunk_id, quote=c.quote) for c in r.citations],
        rationale="x",
    )
    assert derive_finding(control, extracted, settings.decision.rule).status is DraftStatus.NOT_MET


def test_over_long_quote_stays_invalid_even_if_it_exists_elsewhere(
    settings: Settings,
) -> None:
    limit = settings.verification.max_quote_chars
    long_text = "Alpha beta gamma. " * (limit // 10 + 2)
    chunks = [_chunk("d:p001:c000", OTHER), _chunk("d:p002:c000", long_text, 2)]
    quote = long_text[: limit + 1]
    r = _check(
        CitationChecker(settings.verification), chunks, "d:p001:c000", quote, DraftStatus.MET
    )
    assert not r.ok and not r.citations[0].valid and not r.citations[0].relocated


def test_problems_never_contain_quote_text(checker: CitationChecker) -> None:
    quote = "ZEBRA-SECRET-QUOTE nowhere"
    chunks = [_chunk("d:p001:c000", OTHER)]
    r = _check(checker, chunks, "d:p001:c000", quote, DraftStatus.MET)
    assert r.problems and all("ZEBRA" not in p for p in r.problems)


def test_relocated_citations_satisfy_a_required_status(
    checker: CitationChecker, settings: Settings
) -> None:
    assert DraftStatus.MET.value in settings.verification.require_citation_for
    chunks = [_chunk("d:p001:c000", OTHER), _chunk("d:p002:c000", SENTENCE, 2)]
    r = _check(checker, chunks, "d:p001:c000", SENTENCE, DraftStatus.MET)
    assert r.ok and r.problems == [] and all(c.relocated for c in r.citations)


def test_relocation_is_deterministic(checker: CitationChecker) -> None:
    chunks = [_chunk("d:p001:c000", OTHER), _chunk("d:p002:c000", SENTENCE, 2)]
    a = _check(checker, chunks, "d:p001:c000", SENTENCE, DraftStatus.MET)
    b = _check(checker, list(reversed(chunks)), "d:p001:c000", SENTENCE, DraftStatus.MET)
    assert a == b
