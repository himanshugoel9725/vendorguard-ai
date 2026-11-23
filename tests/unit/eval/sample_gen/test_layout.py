"""wrap_lines and block_cost."""

import pytest

from vendorguard.eval.sample_gen.layout import HEADING_COST, TITLE_COST, block_cost, wrap_lines
from vendorguard.eval.sample_gen.models import Block


def test_empty_text_gives_no_lines() -> None:
    assert wrap_lines("", 20) == []
    assert wrap_lines("   ", 20) == []


def test_wraps_at_spaces_within_width() -> None:
    text = "alpha beta gamma delta epsilon zeta eta theta " * 5
    lines = wrap_lines(text, 25)
    assert len(lines) > 1
    assert all(len(line) <= 25 for line in lines)
    assert " ".join(lines) == " ".join(text.split())


def test_hyphenated_words_are_never_broken() -> None:
    lines = wrap_lines("use multi-factor authentication for all admin accounts", 15)
    assert any("multi-factor" in line for line in lines)


def test_long_word_is_kept_whole() -> None:
    word = "x" * 50
    assert wrap_lines(f"a {word} b", 10) == ["a", word, "b"]


def test_unicode_wraps() -> None:
    assert wrap_lines("café naïve résumé", 9) == ["café", "naïve", "résumé"]


def test_wrapping_is_deterministic() -> None:
    text = "word " * 200
    assert wrap_lines(text, 33) == wrap_lines(text, 33)


def test_fixed_costs_for_title_subtitle_heading() -> None:
    assert block_cost(Block(kind="title", text="T"), 88) == TITLE_COST == 3
    assert block_cost(Block(kind="subtitle", text="S " * 100), 88) == HEADING_COST == 2
    assert block_cost(Block(kind="heading", text="H"), 88) == 2


@pytest.mark.parametrize("kind", ["body", "injection"])
def test_body_cost_is_wrapped_lines_plus_one(kind: str) -> None:
    text = "word " * 60
    block = Block(kind=kind, text=text)  # type: ignore[arg-type]
    assert block_cost(block, 20) == len(wrap_lines(text, 20)) + 1
    assert block_cost(Block(kind="body", text="short"), 88) == 2
