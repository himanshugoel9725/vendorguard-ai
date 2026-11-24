"""Edge tests for the citation checker (windows, unicode, limits, determinism)."""

import pytest

from vendorguard.config_models.scoring import VerificationSettings
from vendorguard.models.evidence import Chunk, DraftCitation
from vendorguard.models.finding import DraftStatus
from vendorguard.verification.citation_check import CitationChecker, best_window_similarity

SRC = (
    "Access reviews run every quarter. All laptops use full-disk encryption. Logs are kept a year."
)


def _checker(min_sim: float = 0.9, max_chars: int = 400) -> CitationChecker:
    return CitationChecker(
        VerificationSettings(
            citation_min_similarity=min_sim,
            max_quote_chars=max_chars,
            require_citation_for=["met", "partial"],
        )
    )


def _chunk(text: str, cid: str = "d:p001:c000", page: int = 2) -> Chunk:
    return Chunk(chunk_id=cid, doc_id="d", page=page, text=text, char_start=0, char_end=len(text))


def test_empty_quote_scores_zero() -> None:
    assert best_window_similarity(SRC, "") == 0.0


def test_no_shared_characters_scores_zero() -> None:
    assert best_window_similarity("aaaa", "zzzz") == 0.0


def test_substring_scores_one() -> None:
    assert best_window_similarity(SRC, "full-disk encryption") == 1.0


def test_window_similarity_ignores_the_rest_of_a_long_source() -> None:
    quote = "All laptops use full disk encryption."  # one dash dropped
    score = best_window_similarity(SRC, quote)
    assert 0.9 < score < 1.0
    # a longer source around the same sentence does not change the score
    assert best_window_similarity("Intro. " * 50 + SRC + " Outro." * 50, quote) == pytest.approx(
        score, abs=0.02
    )


def test_similarity_is_below_one_and_deterministic_for_near_miss() -> None:
    a = best_window_similarity(SRC, "Logs are kept for a year.")
    assert a == best_window_similarity(SRC, "Logs are kept for a year.")
    assert 0.0 < a < 1.0


def test_threshold_comes_from_settings() -> None:
    chunks = [_chunk(SRC)]
    cit = [DraftCitation(chunk_id="d:p001:c000", quote="All laptops use full disk encryption.")]
    assert _checker(0.9).check(DraftStatus.MET, cit, chunks).ok
    assert not _checker(0.999).check(DraftStatus.MET, cit, chunks).ok


def test_unicode_quote_matches_after_normalisation() -> None:
    chunks = [_chunk("Daten werden verschlüsselt – “AES” genutzt.")]
    cit = [DraftCitation(chunk_id="d:p001:c000", quote='DATEN werden verschlÜsselt - "aes"')]
    r = _checker().check(DraftStatus.MET, cit, chunks)
    assert r.ok and r.citations[0].similarity == 1.0


def test_cjk_and_emoji_quotes() -> None:
    text = "数据已加密。 Backups \U0001f510 daily."
    r = _checker().check(
        DraftStatus.MET,
        [DraftCitation(chunk_id="d:p001:c000", quote="Backups \U0001f510 daily.")],
        [_chunk(text)],
    )
    assert r.ok


def test_max_quote_chars_boundary_from_settings() -> None:
    text = "x" * 50
    chunks = [_chunk(text)]
    at_limit = DraftCitation(chunk_id="d:p001:c000", quote="x" * 10)
    over = DraftCitation(chunk_id="d:p001:c000", quote="x" * 11)
    checker = _checker(max_chars=10)
    assert checker.check_one(at_limit, {"d:p001:c000": chunks[0]}).valid
    bad = checker.check_one(over, {"d:p001:c000": chunks[0]})
    assert not bad.valid and bad.similarity == 0.0 and bad.page == 2 and bad.doc_id == "d"


def test_unknown_chunk_has_no_doc_or_page() -> None:
    c = _checker().check_one(DraftCitation(chunk_id="nope", quote="q"), {})
    assert not c.valid and c.doc_id is None and c.page is None


def test_no_citations_status_rules() -> None:
    chunks = [_chunk(SRC)]
    for status, ok in [
        (DraftStatus.MET, False),
        (DraftStatus.PARTIAL, False),
        (DraftStatus.NOT_MET, True),
        (DraftStatus.NO_EVIDENCE, True),
    ]:
        r = _checker().check(status, [], chunks)
        assert r.ok is ok
        assert r.citations == []


def test_one_bad_quote_fails_even_with_a_good_one_and_problems_hide_quote_text() -> None:
    secret = "TOPSECRETQUOTE not in source"
    r = _checker().check(
        DraftStatus.MET,
        [
            DraftCitation(chunk_id="d:p001:c000", quote="Access reviews run every quarter."),
            DraftCitation(chunk_id="d:p001:c000", quote=secret),
        ],
        [_chunk(SRC)],
    )
    assert not r.ok
    assert r.problems == ["citation 2 is not found in chunk d:p001:c000"]
    assert all("TOPSECRET" not in p for p in r.problems)


def test_empty_chunk_list() -> None:
    cit = [DraftCitation(chunk_id="d:p001:c000", quote="anything")]
    assert not _checker().check(DraftStatus.NOT_MET, cit, []).ok


def test_large_source_is_handled() -> None:
    big = ("Filler sentence number one. " * 3000) + "The vendor rotates keys yearly."
    r = _checker().check(
        DraftStatus.MET,
        [DraftCitation(chunk_id="d:p001:c000", quote="The vendor rotates keys yearly.")],
        [_chunk(big)],
    )
    assert r.ok


def test_deterministic_report() -> None:
    cit = [DraftCitation(chunk_id="d:p001:c000", quote="Logs are kept for a year.")]
    a = _checker().check(DraftStatus.PARTIAL, cit, [_chunk(SRC)])
    b = _checker().check(DraftStatus.PARTIAL, cit, [_chunk(SRC)])
    assert a == b and a.model_dump_json() == b.model_dump_json()


def test_fuzzy_match_keeps_source_words_not_the_doctored_quote() -> None:
    """A quote with 'not' deleted still passes similarity but is replaced by the source text."""
    source = (
        "The vendor does not enforce multi factor authentication for any administrator account."
    )
    chunk = _chunk(source)
    doctored = "The vendor does enforce multi factor authentication for any administrator account."
    report = _checker().check(
        DraftStatus.MET, [DraftCitation(chunk_id=chunk.chunk_id, quote=doctored)], [chunk]
    )
    assert report.citations[0].valid
    assert "not enforce" in report.citations[0].quote
