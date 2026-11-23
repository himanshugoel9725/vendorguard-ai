"""Chunker: IDs, page boundaries, offsets, size, overlap, coverage, and the committed samples."""

import json
import random
from collections.abc import Callable
from pathlib import Path

import pytest

from vendorguard.config import Settings
from vendorguard.config_models.core import ChunkingSettings
from vendorguard.ingest.chunker import chunk_document, chunk_page, sentence_spans
from vendorguard.ingest.loader import load_document
from vendorguard.ingest.text_cleaner import clean_document
from vendorguard.models.document import Document, Page

STEMS = ["brightdock", "nimbara-hr", "nimbara-hr-y2", "quillfield"]
SMALL = ChunkingSettings(chunk_chars=300, overlap_chars=60, min_chunk_chars=80)


def _doc(*texts: str, doc_id: str = "abcdef0123456789") -> Document:
    return Document(
        doc_id=doc_id,
        filename="x.txt",
        media_type="text/plain",
        sha256="0" * 64,
        pages=[Page(number=i, text=t) for i, t in enumerate(texts, start=1)],
    )


def _prose(rng: random.Random, sentences: int) -> str:
    words = ["access", "policy", "data", "review", "customer", "backup", "annual", "secure", "plan"]
    return " ".join(
        " ".join(rng.choice(words) for _ in range(rng.randint(4, 18))).capitalize() + "."
        for _ in range(sentences)
    )


def test_sentence_spans_split_at_sentence_ends_and_paragraph_breaks() -> None:
    text = "One two. Three four!  Five\n\nSix seven? Eight"
    assert [text[a:b] for a, b in sentence_spans(text)] == [
        "One two.", "Three four!", "Five", "Six seven?", "Eight",
    ]  # fmt: skip


def test_sentence_spans_ignore_decimal_points_and_blank_text() -> None:
    assert [(a, b) for a, b in sentence_spans("Use TLS 1.2 or higher.")] == [(0, 22)]
    assert sentence_spans("  \n\n ") == []


def test_chunk_ids_follow_the_documented_format() -> None:
    chunks = chunk_document(_doc("Short page one.", "Short page two."), SMALL)
    assert [c.chunk_id for c in chunks] == ["abcdef012345:p001:c000", "abcdef012345:p002:c000"]
    assert all(c.doc_id == "abcdef0123456789" for c in chunks)


def test_same_input_gives_identical_chunks_and_ids() -> None:
    doc = _doc(_prose(random.Random(1), 40), _prose(random.Random(2), 25))
    assert chunk_document(doc, SMALL) == chunk_document(doc, SMALL)


def test_a_short_page_is_one_chunk_and_an_empty_page_has_none() -> None:
    chunks = chunk_document(_doc("Tiny.", "", "   \n "), SMALL)
    assert [(c.page, c.text) for c in chunks] == [(1, "Tiny.")]


@pytest.mark.parametrize("seed", range(8))
def test_invariants_on_random_pages(seed: int) -> None:
    """Offsets are exact, nothing crosses a page, sizes are bounded and no text is lost."""
    rng = random.Random(seed)
    pages = [_prose(rng, rng.randint(1, 60)) for _ in range(4)]
    doc = _doc(*pages)
    chunks = chunk_document(doc, SMALL)
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    for page in doc.pages:
        mine = [c for c in chunks if c.page == page.number]
        covered = [False] * len(page.text)
        for previous, c in zip([None, *mine], mine, strict=False):
            assert c.text == page.text[c.char_start : c.char_end]
            assert 0 < len(c.text) < SMALL.chunk_chars + SMALL.min_chunk_chars
            if previous:
                assert c.char_start > previous.char_start and c.char_end > previous.char_end
                assert previous.char_end - c.char_start <= SMALL.overlap_chars
            for i in range(c.char_start, c.char_end):
                covered[i] = True
        assert all(covered[i] or ch.isspace() for i, ch in enumerate(page.text))


def test_consecutive_chunks_overlap_by_whole_sentences() -> None:
    sentences = [f"Sentence number {i:02d} is here." for i in range(30)]
    text = " ".join(sentences)
    spans = chunk_page(text, SMALL)
    assert len(spans) > 2
    for (_a1, b1), (a2, _b2) in zip(spans, spans[1:], strict=False):
        assert a2 < b1  # they overlap
        assert text[a2 - 1] == " " or a2 == 0  # and the next chunk starts at a sentence start
        assert text[a2:b1].count(".") >= 1


def test_overlap_zero_gives_disjoint_chunks() -> None:
    settings = ChunkingSettings(chunk_chars=200, overlap_chars=0, min_chunk_chars=50)
    spans = chunk_page(_prose(random.Random(3), 30), settings)
    assert all(b1 <= a2 for (_, b1), (a2, _) in zip(spans, spans[1:], strict=False))


def test_a_sentence_longer_than_a_chunk_is_cut_at_spaces() -> None:
    text = " ".join(["word"] * 200) + "."
    spans = chunk_page(text, SMALL)
    assert len(spans) > 2
    assert all(b - a <= SMALL.chunk_chars for a, b in spans)
    assert all(text[a:b].strip() == text[a:b] and not text[a:b].startswith("ord") for a, b in spans)


def test_a_single_word_longer_than_a_chunk_is_hard_cut() -> None:
    text = "x" * 700
    spans = chunk_page(text, SMALL)
    assert spans[0][0] == 0 and spans[-1][1] == 700
    assert all(b - a <= SMALL.chunk_chars for a, b in spans)


def test_a_short_tail_is_merged_into_the_previous_chunk() -> None:
    """New text shorter than min_chunk_chars joins the previous chunk, exceeding the soft limit."""
    settings = ChunkingSettings(chunk_chars=100, overlap_chars=0, min_chunk_chars=40)
    text = "A" * 45 + ". " + "B" * 45 + ". " + "C" * 10 + "."
    spans = chunk_page(text, settings)
    assert spans == [(0, len(text))]
    assert len(text) > settings.chunk_chars
    assert len(text) < settings.chunk_chars + settings.min_chunk_chars


def test_a_tail_with_enough_new_text_stays_its_own_chunk() -> None:
    settings = ChunkingSettings(chunk_chars=100, overlap_chars=0, min_chunk_chars=40)
    text = "A" * 90 + ". " + "B" * 50 + "."
    assert [text[a:b] for a, b in chunk_page(text, settings)] == ["A" * 90 + ".", "B" * 50 + "."]


def test_overlap_text_does_not_count_as_new_text_in_the_tail() -> None:
    """Only the part of the tail beyond the previous chunk decides whether it is merged."""
    settings = ChunkingSettings(chunk_chars=100, overlap_chars=60, min_chunk_chars=40)
    text = "A" * 50 + ". " + "B" * 40 + ". " + "C" * 20 + "."
    spans = chunk_page(text, settings)
    assert spans == [(0, len(text))]


def test_paragraph_breaks_are_sentence_boundaries() -> None:
    settings = ChunkingSettings(chunk_chars=30, overlap_chars=0, min_chunk_chars=5)
    text = "Heading without a stop\n\nBody sentence one is here."
    assert [text[a:b] for a, b in chunk_page(text, settings)][0] == "Heading without a stop"


@pytest.mark.parametrize("stem", STEMS)
@pytest.mark.parametrize("suffix", ["pdf", "txt"])
def test_every_evidence_sentence_sits_whole_inside_one_chunk_of_its_page(
    stem: str, suffix: str, project_root: Path, settings_override: Callable[..., Settings]
) -> None:
    """With the default chunk size each gold sentence is retrievable as part of a single chunk."""
    s = settings_override()
    doc = clean_document(
        load_document(project_root / f"data/samples/{stem}.{suffix}", s.ingest), s.ingest
    )
    chunks = chunk_document(doc, s.chunking)
    assert chunks and all(c.page == 1 + int(c.chunk_id.split(":p")[1][:3]) - 1 for c in chunks)
    evidence = json.loads((project_root / f"data/samples/{stem}.evidence.json").read_text("utf-8"))
    for control_id, entry in evidence["controls"].items():
        if entry["sentence"]:
            holders = [c for c in chunks if c.page == entry["page"] and entry["sentence"] in c.text]
            assert holders, (stem, suffix, control_id)
