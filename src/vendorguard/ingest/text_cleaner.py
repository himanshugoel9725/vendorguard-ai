"""Clean extracted page text: Unicode, header/footer lines, hyphenation and whitespace.

Order matters. Line-based rules run before whitespace is collapsed:
``normalize_unicode`` -> ``strip_repeated_lines`` -> ``dehyphenate`` -> ``collapse_whitespace``.
The cleaned text is what chunks, citations and quotes refer to; the document's hash and ID still
describe the original bytes.
"""

import math
import re
import unicodedata
from collections import Counter

from vendorguard.config_models.core import IngestSettings
from vendorguard.models.document import Document, Page

SOFT_HYPHEN = "­"
MIN_REPEATS = 2  # a line must occur on at least two pages to count as a header or footer
_DIGITS = re.compile(r"\d+")
_WORD = r"[^\W\d_]+"
_TOKEN = re.compile(rf"{_WORD}(?:-{_WORD})*")
_LINE_BREAK_HYPHEN = re.compile(rf"({_WORD})-\n({_WORD})")
_OTHER_LINE_BREAK_HYPHEN = re.compile(r"(?<=[^\W_])-\n(?=\S)")  # ISO-\n27001, not --- table rules
_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def normalize_unicode(text: str) -> str:
    """NFKC: ligatures, full-width forms and non-breaking spaces become their plain equivalents."""
    return unicodedata.normalize("NFKC", text)


def _zone(lines: list[str], scan_lines: int | None) -> set[int]:
    """Indices of the non-blank lines that may be headers or footers (first and last N)."""
    filled = [i for i, line in enumerate(lines) if line.strip()]
    return set(filled) if scan_lines is None else set(filled[:scan_lines] + filled[-scan_lines:])


def strip_repeated_lines(
    pages: list[str], min_ratio: float, scan_lines: int | None = None
) -> list[str]:
    """Drop lines that repeat on at least ``min_ratio`` of the pages (running headers, footers).

    Only the first and last ``scan_lines`` non-blank lines of a page can be removed (every line when
    ``scan_lines`` is None), so body text such as ``Backups kept 30 days`` is never mistaken for a
    footer. Digit runs are masked when comparing, so ``Page 2 of 9`` and ``Page 3 of 9`` count as
    the same line. Documents with a single page are left alone.
    """
    if len(pages) < MIN_REPEATS:
        return list(pages)

    def key(line: str) -> str:
        return _DIGITS.sub("#", line.strip())

    split = [text.splitlines() for text in pages]
    zones = [_zone(lines, scan_lines) for lines in split]
    seen: Counter[str] = Counter()
    for lines, zone in zip(split, zones, strict=True):
        seen.update({key(lines[i]) for i in zone})
    needed = max(MIN_REPEATS, math.ceil(round(min_ratio * len(pages), 9)))
    repeated = {k for k, count in seen.items() if count >= needed}
    return [
        "\n".join(line for i, line in enumerate(lines) if not (i in zone and key(line) in repeated))
        for lines, zone in zip(split, zones, strict=True)
    ]


def vocabulary(texts: list[str]) -> set[str]:
    """Lower-case words and hyphenated compounds that occur intact in the texts."""
    return {token.lower() for text in texts for token in _TOKEN.findall(text)}


def dehyphenate(text: str, known: set[str]) -> str:
    """Rejoin words split by a hyphen at a line break, and drop soft hyphens.

    ``authen-\\ntication`` becomes ``authentication`` but ``multi-\\nfactor`` keeps its hyphen when
    ``multi-factor`` occurs elsewhere in ``known`` (or the joined form does not occur and the next
    word is capitalised or a number). Unknown lower-case continuations are joined.
    """

    def repair(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        if f"{left}-{right}".lower() in known:
            return f"{left}-{right}"
        if f"{left}{right}".lower() in known or right[0].islower():
            return f"{left}{right}"
        return f"{left}-{right}"

    text = text.replace(f"{SOFT_HYPHEN}\n", "").replace(SOFT_HYPHEN, "")
    return _OTHER_LINE_BREAK_HYPHEN.sub("-", _LINE_BREAK_HYPHEN.sub(repair, text))


def collapse_whitespace(text: str) -> str:
    """One space between words, soft line breaks joined, one blank line between paragraphs."""
    text = _HORIZONTAL_SPACE.sub(" ", text)
    paragraphs = (" ".join(p.split()) for p in _PARAGRAPH_BREAK.split(text))
    return "\n\n".join(p for p in paragraphs if p)


def clean_document(document: Document, settings: IngestSettings) -> Document:
    """Return the document with every page cleaned (identity, hash and page numbers are kept)."""
    texts = [normalize_unicode(page.text) for page in document.pages]
    if settings.strip_repeated_lines:
        texts = strip_repeated_lines(
            texts, settings.repeated_line_min_ratio, settings.repeated_line_scan_lines
        )
    known = vocabulary(texts)
    cleaned = [collapse_whitespace(dehyphenate(text, known)) for text in texts]
    pages = [
        Page(number=p.number, text=text) for p, text in zip(document.pages, cleaned, strict=True)
    ]
    return document.model_copy(update={"pages": pages})


__all__ = [
    "clean_document",
    "collapse_whitespace",
    "dehyphenate",
    "normalize_unicode",
    "strip_repeated_lines",
    "vocabulary",
]
