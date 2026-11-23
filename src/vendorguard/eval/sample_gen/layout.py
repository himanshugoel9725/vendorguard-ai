"""Line wrapping and page-budget costs shared by the composer and the PDF renderer."""

import textwrap

from vendorguard.eval.sample_gen.models import Block

TITLE_COST = 3  # lines of vertical space a block takes, including the gap after it
HEADING_COST = 2


def wrap_lines(text: str, width: int) -> list[str]:
    """Wrap at spaces only, so hyphenated words such as ``multi-factor`` are never broken."""
    return textwrap.wrap(text, width=width, break_on_hyphens=False, break_long_words=False)


def block_cost(block: Block, wrap_chars: int) -> int:
    """Lines of page budget the block needs."""
    if block.kind == "title":
        return TITLE_COST
    if block.kind in ("subtitle", "heading"):
        return HEADING_COST
    return len(wrap_lines(block.text, wrap_chars)) + 1


__all__ = ["block_cost", "wrap_lines"]
