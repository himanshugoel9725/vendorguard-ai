"""Text cleaner: one group of tests per rule, then the pipeline on the committed samples."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.ingest.loader import load_document
from vendorguard.ingest.text_cleaner import (
    clean_document,
    collapse_whitespace,
    dehyphenate,
    normalize_unicode,
    strip_repeated_lines,
    vocabulary,
)
from vendorguard.models.document import Document, Page

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]


def _doc(*texts: str) -> Document:
    return Document(
        doc_id="d" * 16,
        filename="x.txt",
        media_type="text/plain",
        sha256="0" * 64,
        pages=[Page(number=i, text=t) for i, t in enumerate(texts, start=1)],
    )


# --- rule 1: Unicode ---------------------------------------------------------------------------


def test_nfkc_turns_ligatures_and_nbsp_into_plain_text() -> None:
    assert normalize_unicode("ﬁrewall policy ＡＢ") == "firewall policy AB"


def test_nfkc_leaves_plain_ascii_unchanged() -> None:
    assert normalize_unicode("TLS 1.2 & AES-256") == "TLS 1.2 & AES-256"


# --- rule 2: repeated header / footer lines ----------------------------------------------------


def test_footer_with_changing_page_number_is_removed() -> None:
    bodies = ["alpha text", "beta text", "gamma text", "delta text"]
    pages = [f"{b}\nAcme - Page {n} of 4" for n, b in enumerate(bodies, start=1)]
    assert strip_repeated_lines(pages, 0.6) == bodies


def test_body_lines_that_differ_only_in_digits_count_as_repeated() -> None:
    """Known trade-off of masking digits: such lines on most pages are treated as running text."""
    pages = [f"Version {n}" for n in range(1, 4)]
    assert strip_repeated_lines(pages, 0.6) == ["", "", ""]


def test_line_below_the_ratio_is_kept() -> None:
    pages = ["Header\nA", "Header\nB", "C", "D", "E"]  # Header on 2 of 5 pages = 0.4
    assert strip_repeated_lines(pages, 0.6) == pages
    assert strip_repeated_lines(pages, 0.4) == ["A", "B", "C", "D", "E"]


def test_line_at_exactly_the_ratio_is_removed() -> None:
    pages = ["Top\nA", "Top\nB", "Top\nC", "D", "E"]  # 3 of 5 = 0.6
    assert [p for p in strip_repeated_lines(pages, 0.6)] == ["A", "B", "C", "D", "E"]


def test_single_page_documents_are_never_stripped() -> None:
    assert strip_repeated_lines(["Only page\nPage 1"], 0.0) == ["Only page\nPage 1"]


def test_a_line_on_only_one_page_is_never_a_header() -> None:
    pages = ["unique\nA", "B"]
    assert strip_repeated_lines(pages, 0.0) == pages  # needs at least two occurrences


def test_blank_lines_are_not_counted_or_removed() -> None:
    pages = ["A\n\nB", "C\n\nD", "E\n\nF"]
    assert strip_repeated_lines(pages, 0.6) == pages


# --- rule 3: hyphenation -----------------------------------------------------------------------


def test_split_word_is_rejoined() -> None:
    known = vocabulary(["authentication is required"])
    assert dehyphenate("strong authen-\ntication", known) == "strong authentication"


def test_compound_that_occurs_elsewhere_keeps_its_hyphen() -> None:
    known = vocabulary(["multi-factor authentication is on"])
    assert dehyphenate("uses multi-\nfactor logins", known) == "uses multi-factor logins"


def test_unknown_lowercase_continuation_is_joined() -> None:
    assert dehyphenate("encryp-\ntion", set()) == "encryption"


def test_capitalised_or_numeric_continuation_keeps_the_hyphen() -> None:
    assert dehyphenate("ISO-\n27001 and Wi-\nFi", set()) == "ISO-27001 and Wi-Fi"


def test_soft_hyphens_are_removed() -> None:
    assert dehyphenate("pass­word and fire­\nwall", set()) == "password and firewall"


def test_hyphen_inside_a_line_is_untouched() -> None:
    assert (
        dehyphenate("role-based access - least privilege", set())
        == "role-based access - least privilege"
    )


def test_vocabulary_has_words_and_compounds_lowercased() -> None:
    assert {"multi-factor", "tls", "access"} <= vocabulary(["Multi-Factor TLS access, 2FA"])


# --- rule 4: whitespace ------------------------------------------------------------------------


def test_runs_of_spaces_and_tabs_become_one_space() -> None:
    assert collapse_whitespace("a  \t b   c") == "a b c"


def test_soft_line_breaks_are_joined_and_paragraphs_kept() -> None:
    assert collapse_whitespace("one\ntwo\n\n\n\nthree\n  \nfour") == "one two\n\nthree\n\nfour"


def test_leading_and_trailing_whitespace_is_trimmed() -> None:
    assert collapse_whitespace("  \n hello \n  ") == "hello"
    assert collapse_whitespace(" \n\n ") == ""


# --- pipeline ----------------------------------------------------------------------------------


def test_clean_document_keeps_identity_and_page_numbers() -> None:
    doc = _doc("A  b\nFooter 1", "C d\nFooter 2", "E f\nFooter 3")
    cleaned = clean_document(doc, _settings().ingest)
    assert (cleaned.doc_id, cleaned.sha256, cleaned.filename) == (
        doc.doc_id,
        doc.sha256,
        doc.filename,
    )
    assert [p.number for p in cleaned.pages] == [1, 2, 3]
    assert [p.text for p in cleaned.pages] == ["A b", "C d", "E f"]
    assert doc.pages[0].text == "A  b\nFooter 1"  # the input is not modified


def test_strip_repeated_lines_can_be_switched_off() -> None:
    settings = _settings(ingest={"strip_repeated_lines": False})
    cleaned = clean_document(_doc("A\nFooter 1", "B\nFooter 2"), settings.ingest)
    assert [p.text for p in cleaned.pages] == ["A Footer 1", "B Footer 2"]


def test_cleaning_twice_changes_nothing() -> None:
    doc = _doc(
        "Acme  Page 1\nstrong authen-\ntication", "Acme  Page 2\nmulti-\nfactor multi-factor"
    )
    once = clean_document(doc, _settings().ingest)
    assert clean_document(once, _settings().ingest) == once


@pytest.mark.parametrize("stem", STEMS)
@pytest.mark.parametrize("suffix", ["pdf", "txt"])
def test_samples_keep_every_evidence_sentence_and_lose_the_pdf_footer(
    stem: str, suffix: str, project_root: Path
) -> None:
    """Cleaning must not damage the verbatim evidence, and must remove the PDF page footer."""
    settings = _settings()
    doc = clean_document(
        load_document(project_root / f"data/samples/{stem}.{suffix}", settings.ingest),
        settings.ingest,
    )
    evidence = json.loads((project_root / f"data/samples/{stem}.evidence.json").read_text("utf-8"))
    for control_id, entry in evidence["controls"].items():
        if entry["sentence"]:
            assert entry["sentence"] in doc.pages[entry["page"] - 1].text, (stem, control_id)
    assert not any("Page " in page.text and " of 9" in page.text for page in doc.pages)


def _settings(**overrides: object) -> Settings:
    from vendorguard.config import load_settings

    return load_settings(overrides=overrides or None, env_file=None)


def test_settings_helper_uses_the_real_defaults(settings_override: Callable[..., Settings]) -> None:
    assert _settings().ingest == settings_override().ingest
