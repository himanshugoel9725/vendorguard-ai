"""Plain-text twin of the PDF: same body text and page splits, pages separated by form feeds."""

from vendorguard.eval.sample_gen.models import Block


def render_txt(pages: list[list[Block]]) -> str:
    """One paragraph per line, blank line between paragraphs, ``\\f`` between pages."""
    return "\f".join("\n\n".join(block.text for block in page) for page in pages) + "\n"


__all__ = ["render_txt"]
