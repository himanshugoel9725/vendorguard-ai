"""Tests for the citation checker and text normalisation."""

import pytest

from vendorguard.config_models.scoring import VerificationSettings
from vendorguard.models.evidence import Chunk, DraftCitation
from vendorguard.models.finding import DraftStatus
from vendorguard.verification.citation_check import CitationChecker, best_window_similarity
from vendorguard.verification.text_normalize import normalize_text

TEXT = "All data is encrypted at rest using AES-256. Backups are tested every quarter by the team."


@pytest.fixture
def checker() -> CitationChecker:
    return CitationChecker(
        VerificationSettings(
            citation_min_similarity=0.9,
            max_quote_chars=400,
            require_citation_for=["met", "partial"],
        )
    )


@pytest.fixture
def chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id="d:p001:c000", doc_id="d", page=3, text=TEXT, char_start=0, char_end=len(TEXT)
        )
    ]


def _run(
    checker: CitationChecker,
    chunks: list[Chunk],
    quote: str,
    status: DraftStatus = DraftStatus.MET,
    cid: str = "d:p001:c000",
):
    return checker.check(status, [DraftCitation(chunk_id=cid, quote=quote)], chunks)


def test_exact_quote_valid_and_enriched(checker: CitationChecker, chunks: list[Chunk]) -> None:
    r = _run(checker, chunks, "All data is encrypted at rest using AES-256.")
    assert r.ok and r.citations[0].similarity == 1.0
    assert (r.citations[0].doc_id, r.citations[0].page) == ("d", 3)


def test_case_and_whitespace_pass(checker: CitationChecker, chunks: list[Chunk]) -> None:
    assert _run(checker, chunks, "ALL  data is\n encrypted   AT rest").ok


def test_curly_quotes_and_dashes_normalised() -> None:
    assert normalize_text("It’s “AES–256”") == 'it\'s "aes-256"'


def test_fabricated_quote_rejected(checker: CitationChecker, chunks: list[Chunk]) -> None:
    r = _run(checker, chunks, "We hold an ISO 27001 certificate issued in 2024.")
    assert not r.ok and r.citations[0].valid is False


def test_unknown_chunk_invalid(checker: CitationChecker, chunks: list[Chunk]) -> None:
    r = _run(checker, chunks, "ZEBRA quote that is nowhere at all", cid="nope")
    assert not r.ok and r.citations[0].doc_id is None and not r.citations[0].relocated


def test_unknown_chunk_id_with_a_real_quote_is_relocated(
    checker: CitationChecker, chunks: list[Chunk]
) -> None:
    r = _run(checker, chunks, "All data is encrypted", cid="nope")
    c = r.citations[0]
    assert r.ok and c.relocated and c.chunk_id == "d:p001:c000" and c.page == 3


def test_small_typo_passes_large_edit_fails() -> None:
    assert (
        best_window_similarity(
            "backups are tested every quarter", "backups are tested evry quarter"
        )
        >= 0.9
    )
    assert (
        best_window_similarity(
            "backups are tested every quarter", "backups are never tested at all"
        )
        < 0.9
    )


def test_status_requiring_citation_needs_one(checker: CitationChecker, chunks: list[Chunk]) -> None:
    assert not checker.check(DraftStatus.MET, [], chunks).ok
    assert checker.check(DraftStatus.NO_EVIDENCE, [], chunks).ok
    assert checker.check(DraftStatus.NOT_MET, [], chunks).ok


def test_overlong_quote_invalid(chunks: list[Chunk]) -> None:
    c = CitationChecker(
        VerificationSettings(
            citation_min_similarity=0.9, max_quote_chars=10, require_citation_for=[]
        )
    )
    assert not _run(c, chunks, "All data is encrypted at rest").ok
